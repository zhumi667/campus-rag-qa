"""src/corpus_admin.py — 语料导入编排（管理员功能）

★ 设计要点

1. **两阶段导入，人工把关**
   stage（暂存）→ 敏感扫描 → 解析预览 → 管理员确认 → 入库 → 跑流水线
   未经确认的文件永远不进 data/raw/，也就永远不会被检索到。

2. **doc_id 由管理员指定，而不是从文件名推断**
   原命令行流程把「文件名 → doc_id」写死在 01_parse.py 的 FILE_NAME_MAP 里。
   管理员导入时无法预知文件名，因此改为：元数据登记在 documents.csv，解析时查表。
   两种入口（命令行 / 管理员）共用同一条路径。

3. **入库前先备份 documents.csv**
   导入失败时可回滚元数据，避免留下"有记录但没文件"的脏状态。

4. **流水线跑完必须失效检索器缓存**
   src/retriever.py 的 _RETRIEVERS 是模块级单例字典。不失效的话，
   新语料入库后问答仍走旧索引 —— 表现为"导入成功但问不出新内容"。

5. **staging 目录不进 raw/**
   上传的原始文件先落在 data/_staging/，确认后才移动。
"""
import csv
import json
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import config
from src import chunker, loader, sensitive, utils

logger = utils.get_logger("corpus_admin")

STAGING_DIR = config.BASE_DIR / "data" / "_staging"
SUPPORTED_EXTS = {".pdf", ".docx", ".html", ".htm", ".txt"}

# documents.csv 的 14 列（与 03_register.py 严格一致，勿改顺序）
META_FIELDS = [
    "doc_id", "title", "family_id", "version", "issuer",
    "publish_date", "effective_date", "expire_date", "source_url",
    "file_type", "status", "raw_path", "text_path", "notes",
]
# ★ 管理员在导入时【必须自己填】的字段。
#   注意不含 raw_path / text_path —— 这两个由 confirm_import() 从 staging 推导，
#   管理员无法预知（文件名带 staging_id 前缀）。03_register.py 里它们属必填，
#   是因为那份表的路径是人工写死的；此处语境不同，故分开定义。
USER_REQUIRED_FIELDS = ["doc_id", "title", "family_id", "version",
                        "file_type", "status"]

DOC_ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,40}$")


# ════════════════════════════════════════════════════════════ 元数据表读写
def read_meta_csv() -> list:
    """读 documents.csv；文件不存在返回空表。"""
    p = config.META_CSV
    if not p.exists():
        return []
    with open(p, encoding="utf-8-sig", newline="") as f:
        return [dict(r) for r in csv.DictReader(f)]


def write_meta_csv(rows: list) -> None:
    """整表重写（列顺序固定）。"""
    p = config.META_CSV
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=META_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in META_FIELDS})


def get_meta(doc_id: str) -> dict | None:
    for r in read_meta_csv():
        if r.get("doc_id") == doc_id:
            return r
    return None


def lookup_doc_id_by_filename(filename: str) -> str | None:
    """按 raw_path 的文件名反查 doc_id（供 01_parse 使用，替代硬编码 map）。"""
    for r in read_meta_csv():
        raw = (r.get("raw_path") or "").replace("\\", "/")
        if raw and Path(raw).name == filename:
            return r.get("doc_id") or None
    return None


# ════════════════════════════════════════════════════════════ 暂存
def save_uploads(files: list) -> list:
    """批量保存上传文件到 staging。

    files: [(filename, content_bytes), ...]
    返回 [{ok, staging_id, filename, size, ext} 或 {ok:False, filename, error}, ...]

    ★ 单个文件失败不影响其余 —— 校园资料网一次下载的多份文件常有格式不一致、
      或夹带扫描版 PDF 的情况，逐个失败比整体回滚更实用。
    """
    out = []
    for filename, content in files:
        try:
            info = save_upload(filename, content)
            out.append({"ok": True, **info})
        except Exception as e:
            out.append({"ok": False, "filename": filename,
                        "size": len(content or b""),
                        "ext": Path(filename).suffix.lower().lstrip("."),
                        "error": f"{type(e).__name__}: {e}"})
    return out


def save_upload(filename: str, content: bytes) -> dict:
    """把上传文件写入 staging，返回 staging 标识。"""
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTS:
        raise ValueError(f"不支持的文件类型 {ext}；支持：{', '.join(sorted(SUPPORTED_EXTS))}")
    if not content:
        raise ValueError("文件内容为空")

    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    sid = uuid.uuid4().hex[:12]
    safe_name = _safe_filename(filename)
    dest = STAGING_DIR / f"{sid}__{safe_name}"
    dest.write_bytes(content)
    return {
        "staging_id": sid,
        "filename": safe_name,
        "size": len(content),
        "ext": ext.lstrip("."),
        "path": str(dest),
    }


def _safe_filename(name: str) -> str:
    """去掉路径成分与危险字符，保留中文（语料文件名多为中文）。"""
    name = Path(name).name
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    return name.strip() or "unnamed"


def staging_path(staging_id: str) -> Path | None:
    """按 staging_id 找回文件（文件名里带 id 前缀）。"""
    if not STAGING_DIR.exists():
        return None
    for p in STAGING_DIR.iterdir():
        if p.is_file() and p.name.startswith(f"{staging_id}__"):
            return p
    return None


def staging_list() -> list:
    """列出所有待处理的上传文件。"""
    if not STAGING_DIR.exists():
        return []
    out = []
    for p in sorted(STAGING_DIR.iterdir()):
        if not p.is_file():
            continue
        sid, _, orig = p.name.partition("__")
        out.append({
            "staging_id": sid,
            "filename": orig or p.name,
            "size": p.stat().st_size,
            "uploaded_at": time.strftime("%Y-%m-%d %H:%M:%S",
                                         time.localtime(p.stat().st_mtime)),
        })
    return out


def discard_staging(staging_id: str) -> bool:
    p = staging_path(staging_id)
    if p and p.exists():
        p.unlink()
        return True
    return False


# ════════════════════════════════════════════════════════════ 预览（解析 + 扫描）
@dataclass
class Preview:
    staging_id: str
    filename: str
    file_type: str
    text_len: int
    paragraph_count: int
    table_count: int
    sample: str                      # 前若干段，供管理员核对
    scan: dict = field(default_factory=dict)
    suggested_doc_id: str = ""
    suggested_title: str = ""
    error: str = ""


def preview(staging_id: str, sample_chars: int = 1200) -> Preview:
    """解析上传文件并做敏感扫描，产出预览（不落任何正式目录）。"""
    p = staging_path(staging_id)
    if p is None:
        raise FileNotFoundError(f"未找到暂存文件：{staging_id}")

    filename = p.name.partition("__")[2] or p.name
    try:
        doc = loader.load_any(p)
    except Exception as e:
        return Preview(staging_id=staging_id, filename=filename,
                       file_type=p.suffix.lstrip("."), text_len=0,
                       paragraph_count=0, table_count=0, sample="",
                       error=f"解析失败：{type(e).__name__}: {e}")

    paras = [x["text"].strip() for x in doc.paragraphs if x["text"].strip()]
    full = "\n\n".join(paras)
    tables = getattr(doc, "table_paragraphs", None) or []
    scan = sensitive.scan_text(full).summary()

    return Preview(
        staging_id=staging_id,
        filename=filename,
        file_type=p.suffix.lstrip("."),
        text_len=len(full),
        paragraph_count=len(paras),
        table_count=len(tables),
        sample=full[:sample_chars] + ("…" if len(full) > sample_chars else ""),
        scan=scan,
        suggested_doc_id=_suggest_doc_id(filename),
        suggested_title=Path(filename).stem,
    )


def _suggest_doc_id(filename: str) -> str:
    """从文件名猜一个 doc_id（管理员可改）。规则：类型前缀 + 年份。"""
    stem = Path(filename).stem
    year = ""
    m = re.search(r"(20\d{2})", stem)
    if m:
        year = f"_{m.group(1)}"
    prefix = "doc"
    for kw, pre in [("培养方案", "pyfa"), ("学籍", "xjgl"), ("考试", "kshgl"),
                    ("转专业", "zzy"), ("奖学金", "jxj"), ("实验室", "sysaq"),
                    ("通知", "tz"), ("指南", "zn"), ("手册", "sc")]:
        if kw in stem:
            prefix = pre
            break
    return f"{prefix}{year}" if year else prefix


# ════════════════════════════════════════════════════════════ 确认入库
def validate_meta(meta: dict, allow_overwrite: bool = False) -> list:
    """校验元数据，返回错误列表（空表示通过）。"""
    errs = []
    for f in USER_REQUIRED_FIELDS:
        if not str(meta.get(f, "")).strip():
            errs.append(f"必填字段为空：{f}")
    doc_id = str(meta.get("doc_id", "")).strip()
    if doc_id and not DOC_ID_RE.match(doc_id):
        errs.append(f"doc_id 不合法：{doc_id}（应形如 pyfa_xxx_2025，小写字母数字下划线）")
    if doc_id and get_meta(doc_id) and not allow_overwrite:
        errs.append(f"doc_id 已存在：{doc_id}（如需替换请勾选「覆盖同名文档」）")
    if str(meta.get("status", "")) not in ("active", "inactive", "draft"):
        errs.append("status 只能是 active / inactive / draft")
    if str(meta.get("file_type", "")) not in ("pdf", "docx", "html", "txt"):
        errs.append("file_type 只能是 pdf / docx / html / txt")
    for f in ("publish_date", "effective_date", "expire_date"):
        v = str(meta.get(f, "")).strip()
        if v and not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            errs.append(f"{f} 格式应为 YYYY-MM-DD：{v}")
    return errs


def confirm_import(staging_id: str, meta: dict, allow_overwrite: bool = False) -> dict:
    """把暂存文件正式入库：移动到 raw/ + 解析到 text/ + 登记 documents.csv。

    只做「入库」这一步；切分与建索引由 run_pipeline() 负责。
    """
    p = staging_path(staging_id)
    if p is None:
        raise FileNotFoundError(f"未找到暂存文件：{staging_id}")

    meta = dict(meta)
    errs = validate_meta(meta, allow_overwrite)
    if errs:
        raise ValueError("元数据校验未通过：" + "；".join(errs))

    doc_id = meta["doc_id"].strip()
    filename = p.name.partition("__")[2] or p.name
    raw_dest = config.RAW_DIR / filename
    text_dest = config.TEXT_DIR / f"{doc_id}.txt"

    if raw_dest.exists() and not allow_overwrite:
        raise FileExistsError(f"data/raw/ 下已存在同名文件：{filename}")

    # ---- 备份 documents.csv（失败可回滚）----
    backup = None
    if config.META_CSV.exists():
        backup = config.META_CSV.with_suffix(".csv.import_bak")
        shutil.copy2(config.META_CSV, backup)

    try:
        # 1) staging → raw/
        config.RAW_DIR.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p), str(raw_dest))

        # 2) 解析 → text/
        doc = loader.load_any(raw_dest)
        paras = [x["text"].strip() for x in doc.paragraphs if x["text"].strip()]
        full = "\n\n".join(paras)
        if not full.strip():
            raise ValueError("解析结果为空（可能是扫描版 PDF 或纯图片文档），已中止导入")
        config.TEXT_DIR.mkdir(parents=True, exist_ok=True)
        text_dest.write_text(full, encoding="utf-8")

        # 3) 登记 documents.csv（覆盖或追加）
        rows = read_meta_csv()
        row = {k: str(meta.get(k, "") or "") for k in META_FIELDS}
        row["doc_id"] = doc_id
        row["raw_path"] = f"data/raw/{filename}"
        row["text_path"] = f"data/text/{doc_id}.txt"
        row.setdefault("status", "active")
        idx = next((i for i, r in enumerate(rows) if r.get("doc_id") == doc_id), None)
        if idx is not None:
            rows[idx] = row
        else:
            rows.append(row)
        write_meta_csv(rows)

    except Exception:
        # 回滚：还原元数据、撤回落盘文件
        if backup and backup.exists():
            shutil.copy2(backup, config.META_CSV)
        if raw_dest.exists() and p is not None and not p.exists():
            try:
                shutil.move(str(raw_dest), str(p))
            except Exception:
                pass
        if text_dest.exists():
            try:
                text_dest.unlink()
            except Exception:
                pass
        raise
    finally:
        if backup and backup.exists():
            backup.unlink()

    return {
        "doc_id": doc_id,
        "filename": filename,
        "raw_path": str(raw_dest),
        "text_path": str(text_dest),
        "text_len": len(full),
        "paragraph_count": len(paras),
    }


# ════════════════════════════════════════════════════════════ 流水线（切分 + 建索引）
def run_pipeline(strategy: str = "recursive"):
    """重跑切分与建索引。逐阶段 yield 进度事件（供 SSE 推送）。

    产出事件形如：
        {"stage": "chunk", "status": "running", "message": "...", "progress": 0.3}
        {"stage": "done",  "status": "ok",      "message": "...", "detail": {...}}
    """
    from src.indexer import DenseIndex

    # ---- 阶段 1：切分 ----
    yield {"stage": "chunk", "status": "running", "message": "正在切分全部语料…"}
    t0 = time.perf_counter()
    docs = chunker.load_documents(config.TEXT_DIR, config.META_CSV)
    all_chunks, failed = [], []
    total = max(len(docs), 1)
    for i, (doc_id, text, meta) in enumerate(docs, start=1):
        try:
            all_chunks.extend(chunker.chunk_document(doc_id, text, meta))
        except Exception as e:
            failed.append({"doc_id": doc_id, "error": str(e)})
        if i % 3 == 0 or i == total:
            yield {"stage": "chunk", "status": "running",
                   "message": f"切分 {i}/{total} 份",
                   "progress": round(i / total, 3)}
    config.CHUNK_DIR.mkdir(parents=True, exist_ok=True)
    out_jsonl = config.CHUNK_DIR / f"chunks_{strategy}.jsonl"
    utils.write_jsonl(out_jsonl, all_chunks)
    chunk_ms = int((time.perf_counter() - t0) * 1000)
    yield {"stage": "chunk", "status": "done",
           "message": f"切分完成：{len(all_chunks)} 块（{len(docs)} 份文档，失败 {len(failed)}）",
           "detail": {"chunks": len(all_chunks), "docs": len(docs),
                      "failed": failed, "ms": chunk_ms}}

    # ---- 阶段 2：嵌入与建索引 ----
    yield {"stage": "index", "status": "running",
           "message": f"正在向量化 {len(all_chunks)} 个块…（首次会加载 BGE 模型）"}
    t1 = time.perf_counter()
    out_dir = config.INDEX_DIR / strategy
    idx = DenseIndex.build(chunks=all_chunks, out_dir=out_dir, strategy=strategy)
    index_ms = int((time.perf_counter() - t1) * 1000)
    # ★ size / dim 是 DenseIndex 的 property，不是方法（写成 idx.size() 会 TypeError）
    n_vec, n_dim = idx.size, idx.dim
    yield {"stage": "index", "status": "done",
           "message": f"索引完成：{n_vec} 个向量 / {n_dim} 维",
           "detail": {"size": n_vec, "dim": n_dim, "ms": index_ms}}

    # ---- 阶段 3：失效检索器缓存（★ 不做这步会「导入成功但问不出新内容」）----
    yield {"stage": "reload", "status": "running", "message": "正在重新加载检索器…"}
    t2 = time.perf_counter()
    n = invalidate_caches()
    reload_ms = int((time.perf_counter() - t2) * 1000)
    yield {"stage": "reload", "status": "done",
           "message": f"检索器已重新加载（清理 {n} 个缓存实例）",
           "detail": {"cleared": n, "ms": reload_ms}}

    yield {"stage": "pipeline", "status": "done",
           "message": "全部完成，新语料已可被检索",
           "detail": {"total_ms": chunk_ms + index_ms + reload_ms}}


def invalidate_caches() -> int:
    """清空检索器与索引的单例缓存，使新索引立即生效。"""
    cleared = 0
    try:
        from src import retriever as _r
        cleared += len(getattr(_r, "_RETRIEVERS", {}))
        _r._RETRIEVERS.clear()
    except Exception as e:
        logger.warning("清理 retriever 缓存失败: %s", e)
    try:
        from src import indexer as _i
        cache = getattr(_i, "_INDEXES", None)
        if isinstance(cache, dict):
            cleared += len(cache)
            cache.clear()
    except Exception as e:
        logger.warning("清理 indexer 缓存失败: %s", e)
    return cleared


# ════════════════════════════════════════════════════════════ 语料总览
def corpus_overview() -> dict:
    """当前语料与索引的概况（供管理页展示）。"""
    rows = read_meta_csv()
    from collections import Counter
    fam = Counter(r.get("family_id", "") for r in rows if r.get("family_id"))
    idx_dir = config.INDEX_DIR / "recursive"
    build_info = {}
    bi = idx_dir / "build_info.json"
    if bi.exists():
        try:
            build_info = json.loads(bi.read_text(encoding="utf-8"))
        except Exception:
            build_info = {}

    chunk_count = 0
    cj = config.CHUNK_DIR / "chunks_recursive.jsonl"
    if cj.exists():
        try:
            chunk_count = sum(1 for line in cj.open(encoding="utf-8") if line.strip())
        except Exception:
            chunk_count = 0

    text_total = 0
    for r in rows:
        tp = r.get("text_path") or ""
        p = config.BASE_DIR / tp
        if p.exists():
            text_total += len(p.read_text(encoding="utf-8", errors="replace"))

    return {
        "docs": len(rows),
        "active_docs": sum(1 for r in rows if r.get("status") == "active"),
        "families": len(fam),
        "multi_version_families": sum(1 for _, c in fam.items() if c > 1),
        "chunks": chunk_count,
        "text_chars": text_total,
        "index_size": build_info.get("num_chunks"),
        "index_dim": build_info.get("dim"),
        "index_built_at": build_info.get("built_at"),
        "index_build_seconds": build_info.get("build_seconds"),
        "staging_pending": len(staging_list()),
    }


def list_docs() -> list:
    """已入库文档列表（附文本文件是否存在、字数）。"""
    out = []
    for r in read_meta_csv():
        tp = config.BASE_DIR / (r.get("text_path") or "")
        rp = config.BASE_DIR / (r.get("raw_path") or "")
        chars = 0
        if tp.exists():
            chars = len(tp.read_text(encoding="utf-8", errors="replace"))
        out.append({
            "doc_id": r.get("doc_id", ""),
            "title": r.get("title", ""),
            "family_id": r.get("family_id", ""),
            "version": r.get("version", ""),
            "status": r.get("status", ""),
            "file_type": r.get("file_type", ""),
            "effective_date": r.get("effective_date", ""),
            "chars": chars,
            "text_exists": tp.exists(),
            "raw_exists": rp.exists(),
        })
    return out


def list_versions(family_id: str) -> list:
    """同一 family 的所有版本（供版本冲突展示）。"""
    return [r for r in list_docs() if r.get("family_id") == family_id]
