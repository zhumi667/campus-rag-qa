"""admin.py — 管理员接口：语料导入与管理

★ 导入流程（两阶段，人工把关）
    ① POST /api/admin/upload           上传文件 → data/_staging/
    ② GET  /api/admin/preview/{sid}    解析 + 敏感扫描 → 预览给管理员核对
    ③ POST /api/admin/confirm/{sid}    确认入库（移动到 raw/、解析到 text/、登记元数据）
    ④ GET  /api/admin/pipeline/stream  确认后跑切分与建索引，SSE 推送进度

★ 为什么确认与流水线分开：
    切分与建索引要重新向量化全部语料（本机约 30s~2min，含模型加载），
    不适合塞进 confirm 的同步响应里。分开后前端能先看到"已入库"，
    再用 SSE 展示流水线进度，超时与断线都不会影响入库结果。

★ 权限：全部使用 Depends(require_admin)，学生访问返回 403。
"""
import json
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sse_starlette.sse import EventSourceResponse

import config
from backend import auth, db
from backend.schemas import (BatchUploadResponse, CorpusOverview, DocItem,
                             ImportConfirmResponse, ImportMeta, ImportRecord,
                             PreviewResponse, StagingItem, UploadResponse)
from src import corpus_admin as ca
from src import utils

logger = utils.get_logger("admin")
router = APIRouter(prefix="/api/admin", tags=["admin"])

# 上传大小上限（
# 语料多为 PDF/Word，实测最大约 14MB；给 3 倍余量，避免一次上传撑爆磁盘与内存）
MAX_UPLOAD_BYTES = 40 * 1024 * 1024
# 单次批量上传的文件数上限（防止一次拖入整个目录导致请求超时）
MAX_BATCH_FILES = 60


@router.get("/overview", response_model=CorpusOverview)
def overview(user: dict = Depends(auth.require_admin)):
    """语料与索引概况。"""
    return ca.corpus_overview()


@router.get("/docs", response_model=list[DocItem])
def docs(user: dict = Depends(auth.require_admin)):
    """已入库文档列表。"""
    return ca.list_docs()


@router.get("/imports", response_model=list[ImportRecord])
def imports(limit: int = 30, user: dict = Depends(auth.require_admin)):
    """最近的导入记录。"""
    return db.list_imports(limit=limit)


@router.get("/staging", response_model=list[StagingItem])
def staging(user: dict = Depends(auth.require_admin)):
    """待处理的上传文件。"""
    return ca.staging_list()


@router.delete("/staging/{staging_id}")
def discard(staging_id: str, user: dict = Depends(auth.require_admin)):
    """丢弃一个待处理文件（不删除已入库文档）。"""
    if not ca.discard_staging(staging_id):
        raise HTTPException(status_code=404, detail="未找到该暂存文件")
    return {"ok": True, "staging_id": staging_id}


@router.post("/upload", response_model=UploadResponse)
async def upload(file: UploadFile = File(...),
                 user: dict = Depends(auth.require_admin)):
    """上传语料文件到暂存区（不进入检索范围）。"""
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"文件过大（{len(content)/1024/1024:.1f}MB），上限 "
                   f"{MAX_UPLOAD_BYTES//1024//1024}MB")
    try:
        info = ca.save_upload(file.filename or "unnamed", content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return UploadResponse(staging_id=info["staging_id"], filename=info["filename"],
                          size=info["size"], ext=info["ext"])


@router.post("/upload-batch", response_model=BatchUploadResponse)
async def upload_batch(files: list[UploadFile] = File(...),
                       user: dict = Depends(auth.require_admin)):
    """批量上传语料文件（一次多选）。

    ★ 与 /upload 的区别：本接口【只落盘、不解析】。
      一次传几十份文档时，逐份解析（PDF 可能数秒）会把请求阻塞很久；
      解析改由前端在"核对"步骤逐份调用 /preview/{staging_id} 完成，可并发、可重试。
    ★ 单个文件失败不影响其余 —— 校园资料网一次下载的多份文件常有格式不一致，
      逐个返回结果比整体失败更实用。
    """
    if not files:
        raise HTTPException(status_code=400, detail="未选择文件")
    if len(files) > MAX_BATCH_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"单次最多 {MAX_BATCH_FILES} 个文件，当前 {len(files)} 个")

    valid, oversize = [], []
    for f in files:
        content = await f.read()
        name = f.filename or "unnamed"
        if len(content) > MAX_UPLOAD_BYTES:
            oversize.append(name)
        else:
            valid.append((name, content))

    results = ca.save_uploads(valid) if valid else []
    for n in oversize:
        results.append({
            "ok": False, "filename": n,
            "error": f"文件超过 {MAX_UPLOAD_BYTES // 1024 // 1024}MB 上限",
        })

    ok_n = sum(1 for r in results if r.get("ok"))
    logger.info("批量上传：成功 %s / 共 %s（操作人 %s）", ok_n, len(results), user["username"])
    return BatchUploadResponse(total=len(results), ok_count=ok_n, items=results)


@router.get("/preview/{staging_id}", response_model=PreviewResponse)
def preview(staging_id: str, user: dict = Depends(auth.require_admin)):
    """解析并扫描暂存文件，返回预览供管理员核对。"""
    try:
        pv = ca.preview(staging_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return PreviewResponse(
        staging_id=pv.staging_id, filename=pv.filename, file_type=pv.file_type,
        text_len=pv.text_len, paragraph_count=pv.paragraph_count,
        table_count=pv.table_count, sample=pv.sample, scan=pv.scan,
        suggested_doc_id=pv.suggested_doc_id, suggested_title=pv.suggested_title,
        error=pv.error,
    )


@router.post("/confirm/{staging_id}", response_model=ImportConfirmResponse)
def confirm(staging_id: str, meta: ImportMeta,
            user: dict = Depends(auth.require_admin)):
    """确认入库：移动到 raw/、解析到 text/、登记 documents.csv。"""
    import_id = uuid.uuid4().hex[:12]
    data = meta.model_dump()
    allow_overwrite = bool(data.pop("allow_overwrite", False))

    # 先落一条记录（便于失败时也能在导入历史里看到）
    src = ca.staging_path(staging_id)
    db.create_import(import_id, source_name=(src.name.partition("__")[2] if src else ""),
                     file_size=(src.stat().st_size if src and src.exists() else 0),
                     user_id=user["user_id"], doc_id=data.get("doc_id", ""),
                     scan={})

    try:
        res = ca.confirm_import(staging_id, data, allow_overwrite=allow_overwrite)
    except FileNotFoundError as e:
        db.update_import(import_id, status="failed", stage="confirm", message=str(e))
        raise HTTPException(status_code=404, detail=str(e))
    except (ValueError, FileExistsError) as e:
        db.update_import(import_id, status="failed", stage="confirm", message=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("导入失败 import_id=%s", import_id)
        db.update_import(import_id, status="failed", stage="confirm",
                         message=f"{type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"导入失败：{e}")

    db.update_import(import_id, status="imported", stage="register",
                     doc_id=res["doc_id"],
                     message="已入库，待执行切分与建索引",
                     detail={"text_len": res["text_len"],
                             "paragraph_count": res["paragraph_count"]})
    logger.info("语料入库 doc_id=%s 由 %s 操作", res["doc_id"], user["username"])
    return ImportConfirmResponse(
        import_id=import_id, doc_id=res["doc_id"], filename=res["filename"],
        text_len=res["text_len"], paragraph_count=res["paragraph_count"],
        message="已入库；请继续执行向量化以使其可被检索",
    )


@router.get("/pipeline/stream")
async def pipeline_stream(import_id: str = "", user: dict = Depends(auth.require_admin)):
    """SSE：跑切分与建索引，逐阶段推送进度。

    帧序：stage*（running/done）→ done/error
    """
    def gen():
        try:
            for ev in ca.run_pipeline():
                if import_id:
                    db.update_import(import_id, stage=ev.get("stage"),
                                     message=ev.get("message", ""),
                                     status=("pipeline_ok" if ev.get("stage") == "pipeline"
                                             else "pipeline_running"),
                                     detail=ev.get("detail"))
                yield {"event": ev.get("status", "message"),
                       "data": json.dumps(ev, ensure_ascii=False)}
            yield {"event": "done",
                   "data": json.dumps({"message": "流水线执行完成"}, ensure_ascii=False)}
        except Exception as e:
            logger.exception("流水线执行失败 import_id=%s", import_id)
            if import_id:
                db.update_import(import_id, status="failed", stage="pipeline",
                                 message=f"{type(e).__name__}: {e}")
            yield {"event": "error",
                   "data": json.dumps({"message": f"{type(e).__name__}: {e}"},
                                      ensure_ascii=False)}

    return EventSourceResponse(gen())


@router.get("/config")
def admin_config(user: dict = Depends(auth.require_admin)):
    """给前端展示的关键参数（只读）。"""
    return {
        "index_dir": str(config.INDEX_DIR),
        "raw_dir": str(config.RAW_DIR),
        "text_dir": str(config.TEXT_DIR),
        "meta_csv": str(config.META_CSV),
        "max_upload_mb": MAX_UPLOAD_BYTES // 1024 // 1024,
        "supported_exts": sorted(ca.SUPPORTED_EXTS),
    }
