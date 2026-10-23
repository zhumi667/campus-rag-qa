"""eval_e4.py — E4「整体基线对比」实验（★只跑 dev，不碰 test）

依次运行 B1 裸模型 / B2 朴素RAG / B3 完整系统，结果追加写入 eval/data/eval_runs.csv，
并打印三者的汇总对比表（整体 + 按 category 分组）。

用法：
    python scripts/eval_e4.py
    python scripts/eval_e4.py --systems b1_bare --limit 5     # 快速冒烟
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根入 path

from eval.baselines import BASELINES  # noqa: E402
from eval.runner import run_eval  # noqa: E402

ROWS = [
    ("检索层", "Recall@1", "recall@1"),
    ("检索层", "Recall@3", "recall@3"),
    ("检索层", "Recall@5", "recall@5"),
    ("检索层", "Recall@10", "recall@10"),
    ("检索层", "MRR", "mrr"),
    ("检索层", "gold_doc_hit@5", "gold_doc_hit"),
    ("行为层", "拒答准确率", "refused_correct"),
    ("行为层", "过度拒答数(可答题被拒)", "over_refusal"),
    ("行为层", "该拒不拒数(拒答题未拒)", "missed_refusal"),
    ("引用", "平均引用数", "cite_avg"),
    ("引用", "有效引用数", "cite_valid"),
    ("耗时", "检索 ms", "retrieve_ms"),
    ("耗时", "判定 ms", "judge_ms"),
    ("耗时", "生成 ms", "generate_ms"),
    ("耗时", "总计 ms", "total_ms"),
]


def print_comparison(summaries: dict):
    names = list(summaries)
    print("\n" + "=" * 96)
    print("E4 三基线对比（dev，整体）")
    print("=" * 96)
    print(f"{'层':<8}{'指标':<24}" + "".join(f"{n:>18}" for n in names))
    print("-" * 96)
    for layer, label, key in ROWS:
        vals = []
        for n in names:
            v = summaries[n]["overall"].get(key, 0)
            vals.append(f"{v:>18.3f}" if isinstance(v, float) else f"{v:>18}")
        print(f"{layer:<8}{label:<24}" + "".join(vals))
    print("-" * 96)
    print(f"{'':<8}{'题数':<24}" + "".join(f"{summaries[n]['n_total']:>18}" for n in names))
    print("=" * 96)

    for cat in ["fact", "procedure", "cross", "refuse"]:
        has = any(summaries[n]["by_category"].get(cat, {}).get("n", 0) for n in names)
        if not has:
            continue
        print(f"\n--- category = {cat} ---")
        print(f"{'指标':<32}" + "".join(f"{n:>18}" for n in names))
        print("-" * 96)
        for _, label, key in ROWS:
            vals = []
            for n in names:
                a = summaries[n]["by_category"].get(cat, {})
                v = a.get(key, 0)
                vals.append(f"{v:>18.3f}" if isinstance(v, float) else f"{v:>18}")
            print(f"{label:<32}" + "".join(vals))


def main():
    parser = argparse.ArgumentParser(description="E4 整体基线对比（只跑 dev）")
    parser.add_argument("--systems", type=str, default="b1_bare,b2_naive,b3_full")
    parser.add_argument("--split", type=str, default="dev")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out-csv", type=str, default=None,
                        help="逐题结果落盘路径（默认 eval/data/eval_runs.csv，追加写）")
    args = parser.parse_args()

    assert args.split == "dev", "★ 本批只允许 split=dev（test 集冻结，最后一次性评估）"

    names = [s.strip() for s in args.systems.split(",") if s.strip()]
    summaries = {}
    for name in names:
        print("\n" + "#" * 96)
        print(f"# 运行基线 {name}   split={args.split}")
        print("#" * 96)
        t0 = time.perf_counter()
        obj = BASELINES[name]()
        print(f"[{name}] 初始化 {time.perf_counter() - t0:.1f}s")
        t1 = time.perf_counter()
        summaries[name] = run_eval(obj, split=args.split, limit=args.limit,
                                   out_csv=args.out_csv)
        print(f"[{name}] 评测完成，耗时 {time.perf_counter() - t1:.1f}s")

    print_comparison(summaries)


if __name__ == "__main__":
    main()
