"""01_parse.py — 批量解析文档到纯文本

用法：
    D:\\Miniconda3\\envs\\campus-rag\\python.exe scripts/01_parse.py --source raw_dev --limit 3
    D:\\Miniconda3\\envs\\campus-rag\\python.exe scripts/01_parse.py --source raw

功能：
    对 data/{source}/ 下每个支持的文档调用 loader.load_any() 解析，
    写入 data/text/{doc_id}.txt（段落用空行分隔）。
    单份失败不中断，末尾打印成功/失败清单。
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根入 path

import argparse
import time

import config  # noqa: E402
from src import loader, utils  # noqa: E402

logger = utils.get_logger("01_parse")

_SUPPORTED_EXTS = {".pdf", ".docx", ".html", ".htm", ".txt"}

# raw 正式语料输出文件名映射：(完整文件名 -> doc_id)，严格精确匹配
FILE_NAME_MAP = {
    # 培养方案（5份，2025级多专业）
    "2025级软件工程专业培养方案(主修).pdf":            "pyfa_ruanjian_2025",
    "2025级计算机科学与技术专业培养方案(主修).pdf":      "pyfa_jisuanji_2025",
    "2025级自动化专业培养方案(主修) .pdf":             "pyfa_zidonghua_2025",
    "2025级电气工程及其自动化专业培养方案(主修).pdf":    "pyfa_dianqi_2025",
    "2025级人工智能专业培养方案(主修).pdf":            "pyfa_rengongzhineng_2025",
    # 校级规章（5份）
    "桂电教〔2025〕27号--关于印发《桂林电子科技大学普通高等教育本科学生学籍管理规定（2025年修订）》的通知.pdf": "xjgl_2025",
    "桂电教〔2020〕15号关于印发《桂林电子科技大学考试管理规定》的通知.pdf": "kshgl_2020",
    "桂电教〔2021〕6号--关于印发《桂林电子科技大学本科生专业分流及转专业管理办法（修订）》的通知.pdf": "zzy_2021",
    "syjaq_2021.pdf": "sysaq_2021",
    "gjjxj_2026.docx": "gjjxj_2026",
    # 专业介绍 / 指南 / 通知（4份）
    "网络工程（应本）-招生信息网.pdf": "wangluo_jieshao",
    "附件4：求职创业补贴系统操作手册（2023版-参考）.docx": "qzcybt_2023",
    "关于开展2026年10月学生体质健康测试工作的通知.docx": "tzjk_2026",
    "通知1：2026年“东方财富杯”全国大学生金融安全知识网络比拼活动参赛说明.docx": "dfcfb_2026",
}


def _make_doc_id(filename: str, source: str) -> str:
    """生成输出文件名（doc_id）

    raw 的解析顺序：
      1) FILE_NAME_MAP —— 初始 14 份文档的精确映射（保留，保证历史行为不变）
      2) documents.csv —— 由「管理员语料导入」登记的文档（按 raw_path 文件名反查）
      这样命令行与管理员两个入口共用同一条解析路径；新增文档无需再改代码。
    raw_dev 仍用文件名 stem。
    """
    if source == "raw":
        doc_id = FILE_NAME_MAP.get(filename)
        if doc_id is None:
            doc_id = _lookup_doc_id_from_meta(filename)
        if doc_id is None:
            raise ValueError(
                f"文件名未登记：{filename!r}。请二选一：\n"
                f"  ① 加入 scripts/01_parse.py 的 FILE_NAME_MAP；\n"
                f"  ② 通过管理页「语料导入」上传（会自动登记 {config.META_CSV.name}）"
            )
        return doc_id
    return Path(filename).stem


def _lookup_doc_id_from_meta(filename: str):
    """按 data/meta/documents.csv 的 raw_path 文件名反查 doc_id。"""
    import csv as _csv
    if not config.META_CSV.exists():
        return None
    try:
        with open(config.META_CSV, encoding="utf-8-sig", newline="") as f:
            for row in _csv.DictReader(f):
                raw = (row.get("raw_path") or "").replace("\\", "/")
                if raw and Path(raw).name == filename:
                    return row.get("doc_id") or None
    except Exception as e:
        logger.warning("读取 %s 失败：%s", config.META_CSV, e)
    return None


def _iter_docs(source_dir: Path, limit):
    """列出待解析文件（按名字排序），支持 limit 截断"""
    files = sorted(
        f for f in source_dir.iterdir()
        if f.is_file() and f.suffix.lower() in _SUPPORTED_EXTS
    )
    return files[:limit] if limit is not None else files


def _write_text(doc_id: str, doc: loader.ParsedDocument, out_dir: Path) -> Path:
    """把解析结果写成 txt，段落用空行分隔"""
    lines = [p["text"].strip() for p in doc.paragraphs if p["text"].strip()]
    out_path = out_dir / f"{doc_id}.txt"
    out_path.write_text("\n\n".join(lines), encoding="utf-8")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="批量解析文档")
    parser.add_argument("--source", choices=["raw", "raw_dev"], default="raw",
                        help="语料来源目录（默认 raw）")
    parser.add_argument("--limit", type=int, default=None,
                        help="只处理前 N 份文档（便于调试）")
    parser.add_argument("--outdir", type=str, default=None,
                        help="显式指定输出目录（默认 raw->data/text/，raw_dev->data/text_dev/）")
    parser.add_argument("--overwrite", action="store_true",
                        help="覆盖已存在的输出文件（默认跳过）")
    args = parser.parse_args()

    src_dir = config.RAW_DIR if args.source == "raw" else config.RAW_DEV_DIR
    if args.outdir:
        out_dir = Path(args.outdir)
    elif args.source == "raw":
        out_dir = config.TEXT_DIR
    else:
        out_dir = config.TEXT_DEV_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    files = _iter_docs(src_dir, args.limit)
    if not files:
        print(f"未在 {src_dir} 找到支持的文档")
        return

    print("=" * 72)
    print(f"解析来源 : {src_dir}")
    print(f"输出目录 : {out_dir}")
    print(f"待处理   : {len(files)} 份")
    print("=" * 72)

    success, failed, skipped = [], [], []
    for f in files:
        doc_id = _make_doc_id(f.name, args.source)
        out_path = out_dir / f"{doc_id}.txt"
        if out_path.exists() and not args.overwrite:
            skipped.append(f.name)
            print(f"[SKIP] {f.name} -> {doc_id}.txt 已存在（--overwrite 可覆盖）")
            continue

        t0 = time.perf_counter()
        try:
            doc = loader.load_any(f)
            out_path = _write_text(doc_id, doc, out_dir)
            elapsed = time.perf_counter() - t0
            pages = doc.pages if doc.pages is not None else "-"
            cn = utils.count_chinese(doc.full_text)
            success.append((f.name, doc_id, pages, cn, elapsed))
            print(f"[OK]   {f.name}")
            print(f"       -> {out_path.name}  页数={pages}  中文字数={cn}  耗时={elapsed:.3f}s")
        except loader.DocumentLoadError as e:
            elapsed = time.perf_counter() - t0
            failed.append((f.name, str(e)))
            print(f"[FAIL] {f.name}  耗时={elapsed:.3f}s")
            print(f"       原因: {e}")
        except Exception as e:  # 兜底，任何异常都不中断整体流程
            elapsed = time.perf_counter() - t0
            failed.append((f.name, f"未知错误: {e}"))
            print(f"[FAIL] {f.name}  耗时={elapsed:.3f}s")
            print(f"       原因: 未知错误 {e}")

    print()
    print("=" * 72)
    print(f"解析完成：成功 {len(success)} / 失败 {len(failed)} / 跳过 {len(skipped)}")
    if success:
        print("成功清单:")
        for name, doc_id, pages, cn, _ in success:
            print(f"  - {name}  ->  {doc_id}.txt  (页数={pages}, 中文字数={cn})")
    if failed:
        print("失败清单:")
        for name, reason in failed:
            print(f"  - {name}  原因: {reason}")
    print("=" * 72)


if __name__ == "__main__":
    main()
