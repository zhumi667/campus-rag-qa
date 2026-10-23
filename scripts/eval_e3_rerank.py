"""eval_e3_rerank.py — E3 重排消融实验（★只跑 dev 集）

- b3_full          ：复用 eval_runs.csv 中已有记录（本脚本【不重跑】）
- b3_rerank        ：召回 top-20 → 重排 → top-5 → 判定 → 生成
- b3_rerank_top10  ：同上，但重排后取 top-10

结果【追加】写入 eval/data/eval_runs.csv（绝不覆盖历史）。唯一自变量 = 重排开关。

用法：
    python scripts/eval_e3_rerank.py                     # 默认跑 b3_rerank
    python scripts/eval_e3_rerank.py --systems b3_rerank,b3_rerank_top10
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根入 path

from eval.baselines import BASELINES  # noqa: E402
from eval.runner import run_eval  # noqa: E402


class _RerankTimingWrap:
    """包装带重排的 system，收集每题重排耗时（避免改动 runner 的固定 CSV 列）。"""

    def __init__(self, system):
        self.system = system
        self.name = system.name
        self.rerank_ms = []

    def __call__(self, question):
        r = self.system(question)
        rm = getattr(self.system.retriever, "last_rerank_elapsed", 0.0)
        self.rerank_ms.append(round(rm * 1000, 1))
        return r


def main():
    parser = argparse.ArgumentParser(description="E3 重排消融（只跑 dev）")
    parser.add_argument("--systems", default="b3_rerank")
    parser.add_argument("--split", default="dev")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 题（冒烟用）")
    parser.add_argument("--out-csv", type=str, default=None, help="落盘路径（默认追加 eval/data/eval_runs.csv）")
    args = parser.parse_args()

    assert args.split == "dev", "★ 本批只允许 split=dev（test 集冻结）"

    for name in [s.strip() for s in args.systems.split(",") if s.strip()]:
        print("\n" + "#" * 92)
        print(f"# 运行 {name}   split={args.split}")
        print("#" * 92)
        t0 = time.perf_counter()
        obj = BASELINES[name]()
        print(f"[{name}] 初始化 {time.perf_counter() - t0:.1f}s")

        wrap = _RerankTimingWrap(obj)
        t1 = time.perf_counter()
        run_eval(wrap, split=args.split, limit=args.limit, out_csv=args.out_csv)
        dt = time.perf_counter() - t1
        print(f"\n[{name}] 评测完成，总耗时 {dt:.1f}s")

        if wrap.rerank_ms:
            n = len(wrap.rerank_ms)
            srt = sorted(wrap.rerank_ms)
            print(f"[{name}] 重排耗时统计: 平均 {sum(wrap.rerank_ms) / n:.1f}ms  "
                  f"中位 {srt[n // 2]:.1f}ms  最小 {srt[0]:.1f}ms  最大 {srt[-1]:.1f}ms  (n={n})")


if __name__ == "__main__":
    main()
