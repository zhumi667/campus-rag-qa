"""05_build_index.py — 建 FAISS 密集向量索引

用法：
    D:\\Miniconda3\\envs\\campus-rag\\python.exe scripts/05_build_index.py
    D:\\Miniconda3\\envs\\campus-rag\\python.exe scripts/05_build_index.py --source raw_dev
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根入 path

import argparse
import time

import config  # noqa: E402
from src import utils  # noqa: E402
from src import embedder  # noqa: E402
from src import indexer  # noqa: E402

logger = utils.get_logger("05_build_index")

_SELF_CHECK_QUESTIONS = [
    "考试不及格可以补考吗",
    "转专业需要什么条件",
    "学生可以申请休学吗",
]


def main():
    parser = argparse.ArgumentParser(description="建 FAISS 索引")
    parser.add_argument("--strategy", choices=["recursive"], default="recursive")
    parser.add_argument("--source", choices=["raw", "raw_dev"], default="raw")
    parser.add_argument("--outdir", type=str, default=None)
    args = parser.parse_args()

    chunk_dir = config.CHUNK_DIR if args.source == "raw" else config.CHUNK_DEV_DIR
    jsonl = chunk_dir / f"chunks_{args.strategy}.jsonl"
    chunks = utils.read_jsonl(jsonl)

    if args.outdir:
        out_dir = Path(args.outdir)
    elif args.source == "raw":
        out_dir = config.INDEX_DIR / args.strategy
    else:
        out_dir = config.INDEX_DEV_DIR / args.strategy

    emb = embedder.get_embedder()

    print("========== 索引构建 ==========")
    print(f"策略: {args.strategy}")
    print(f"块数: {len(chunks)}")
    print(f"维度: {emb.dim}")
    print(f"设备: {emb.device}")
    print(f"索引类型: IndexFlatIP")

    t0 = time.perf_counter()
    source_jsonl = str(jsonl.relative_to(config.BASE_DIR)).replace("\\", "/")
    idx = indexer.DenseIndex.build(
        chunks, embedder=emb, out_dir=out_dir,
        strategy=args.strategy, source_jsonl=source_jsonl,
    )
    print(f"耗时: {time.perf_counter() - t0:.2f}s")

    print()
    print("========== 自检 ==========")

    # 自检1：条数 == 块数
    ok1 = idx.size == len(chunks)
    print(f"[1/4] 索引条数 == 块数: {idx.size} == {len(chunks)} {'✅' if ok1 else '❌'}")

    # 自检2：维度 == 512
    ok2 = idx.dim == 512
    print(f"[2/4] 向量维度: {idx.dim} {'✅' if ok2 else '❌'}")

    # 自检3：自检索
    first_text = chunks[0]["text"]
    r_no = idx.search(first_text, top_k=1, use_query_prefix=False)
    r_yes = idx.search(first_text, top_k=1, use_query_prefix=True)
    no_top = r_no[0] if r_no else {}
    yes_top = r_yes[0] if r_yes else {}
    ok3 = no_top.get("chunk_id") == chunks[0]["chunk_id"] and abs(no_top.get("score", 0) - 1.0) < 0.01
    print(f"[3/4] 自检索（不加query前缀）: top1={no_top.get('chunk_id')} score={no_top.get('score', 0):.4f} {'✅' if ok3 else '❌'}")
    print(f"      自检索（加query前缀）  : top1={yes_top.get('chunk_id')} score={yes_top.get('score', 0):.4f}")

    # 自检4：真实问题检索
    print("[4/4] 真实问题检索:")
    for q in _SELF_CHECK_QUESTIONS:
        print(f"      问题: {q}")
        for r in idx.search(q, top_k=5):
            print(f"        #{r['rank'] + 1} {r['chunk_id']}  {r['score']:.4f}")

    print()
    print(f"输出目录: {out_dir}")


if __name__ == "__main__":
    main()
