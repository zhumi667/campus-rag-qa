"""04_chunk.py — 批量切分，产出 JSONL

用法：
    D:\\Miniconda3\\envs\\campus-rag\\python.exe scripts/04_chunk.py --source raw
    D:\\Miniconda3\\envs\\campus-rag\\python.exe scripts/04_chunk.py --source raw_dev
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根入 path

import argparse
import time

import config  # noqa: E402
from src import utils  # noqa: E402
from src import chunker  # noqa: E402

logger = utils.get_logger("04_chunk")


def main():
    parser = argparse.ArgumentParser(description="批量切分文本，产出 JSONL")
    parser.add_argument("--source", choices=["raw", "raw_dev"], default="raw")
    parser.add_argument("--strategy", choices=["recursive"], default="recursive")
    parser.add_argument("--limit", type=int, default=None, help="只处理前 N 份")
    parser.add_argument("--outdir", type=str, default=None, help="输出目录（默认按 source 分）")
    args = parser.parse_args()

    text_dir = config.TEXT_DIR if args.source == "raw" else config.TEXT_DEV_DIR
    if args.outdir:
        out_dir = Path(args.outdir)
    elif args.source == "raw":
        out_dir = config.CHUNK_DIR
    else:
        out_dir = config.CHUNK_DEV_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"chunks_{args.strategy}.jsonl"

    docs = chunker.load_documents(text_dir, config.META_CSV)
    if args.limit is not None:
        docs = docs[:args.limit]

    print("=" * 72)
    print(f"切分来源 : {text_dir}")
    print(f"输出文件 : {out_file}")
    print(f"待处理   : {len(docs)} 份")
    print("=" * 72)

    t0 = time.perf_counter()
    all_chunks, failed = [], []
    for i, (doc_id, text, meta) in enumerate(docs, start=1):
        t1 = time.perf_counter()
        try:
            chunks = chunker.chunk_document(doc_id, text, meta)
            all_chunks.extend(chunks)
            lens = [c["token_len"] for c in chunks]
            avg = sum(lens) // len(lens) if lens else 0
            mx = max(lens) if lens else 0
            mn = min(lens) if lens else 0
            print(f"[{i}/{len(docs)}] {doc_id}.txt → {len(chunks)} 块 | "
                  f"平均{avg}token 最长{mx} 最短{mn} | 耗时{time.perf_counter() - t1:.2f}s")
        except Exception as e:
            failed.append((doc_id, str(e)))
            print(f"[FAIL] {doc_id}.txt 原因: {e}")

    utils.write_jsonl(out_file, all_chunks)

    # 汇总
    dist = {"<400": 0, "400-600": 0, "600-800": 0, ">800": 0}
    for c in all_chunks:
        t = c["token_len"]
        if t < 400:
            dist["<400"] += 1
        elif t <= 600:
            dist["400-600"] += 1
        elif t <= 800:
            dist["600-800"] += 1
        else:
            dist[">800"] += 1
    total = len(all_chunks)
    pct = lambda n: (n * 100 // total) if total else 0

    field_ok = sum(1 for c in all_chunks
                   if all(k in c for k in chunker.REQUIRED_FIELDS))

    print()
    print("========== 切分完成 ==========")
    print(f"处理文档: {len(docs)} 份（失败 {len(failed)} 份）")
    print(f"总块数: {total}")
    print(f"token 分布: <400: {dist['<400']} ({pct(dist['<400'])}%)  "
          f"400-600: {dist['400-600']} ({pct(dist['400-600'])}%)  "
          f"600-800: {dist['600-800']} ({pct(dist['600-800'])}%)  "
          f">800: {dist['>800']} ({pct(dist['>800'])}%)")
    if field_ok == total:
        print(f"字段完整性: 全部 {total} 块字段齐全 ✅")
    else:
        print(f"字段完整性: {field_ok}/{total} 块字段齐全 ❌")
    print(f"输出文件: {out_file}")
    print(f"耗时: {time.perf_counter() - t0:.2f}s")
    if failed:
        print("失败清单:")
        for doc_id, reason in failed:
            print(f"  - {doc_id}: {reason}")


if __name__ == "__main__":
    main()
