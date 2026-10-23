"""eval_max_check.py — 判定窗口（max_check）消融实验 · 三档正交设计

★ 本批【只做检索 + 判定，不调用生成模型】：
      answer 列写空字符串、generate_ms 记 0。

三档正交设计（固定其它变量，隔离两个因素）：
    system          召回 top_k   max_check   目的
    ─────────────────────────────────────────────────────────
    b3_mc3_r5           5            3       当前基线（应与现有 b3_full 行为一致）
    b3_mc3_r10         10            3       隔离"多召回"的影响（判定窗口不变）
    b3_mc8_r10         10            8       隔离"多看块"的影响（召回不变）

★ 不改 config.TOP_K_FINAL 的默认值（保持 5），top_k 由本脚本显式传入。

结果【追加】写入 eval/data/eval_runs.csv（绝不覆盖历史）。

用法：
    python scripts/eval_max_check.py --limit 10 --out-csv eval/_pilot.csv   # 先导（10 题分层抽样）
    python scripts/eval_max_check.py                                        # 全量 dev 61 题
"""
import argparse
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根入 path

import config  # noqa: E402
from src.retriever import get_retriever  # noqa: E402
from eval.runner import load_questions, run_eval  # noqa: E402

# 三档正交设计
CONFIGS = {
    "b3_mc3_r5": {"top_k": 5, "max_check": 3},
    "b3_mc3_r10": {"top_k": 10, "max_check": 3},
    "b3_mc8_r10": {"top_k": 10, "max_check": 8},
}
CONFIG_ORDER = ["b3_mc3_r5", "b3_mc3_r10", "b3_mc8_r10"]

# 先导抽样配额（按 dev 集构成 33:20:4:4 近似取整，共 10 题）
PILOT_QUOTA = {"fact": 5, "procedure": 3, "cross": 1, "refuse": 1}


class _CountingGenerator:
    """包装 generator 单例，统计 LLM 调用次数（对照本批的调用预算）。"""

    def __init__(self, inner):
        self._inner = inner
        self.calls = 0

    def chat(self, *a, **k):
        self.calls += 1
        return self._inner.chat(*a, **k)

    def __getattr__(self, name):
        return getattr(self._inner, name)


# 包装 generator 单例：verify_answerable 内部会取它，从而被计数
from src import generator as _gen_mod  # noqa: E402

_LLM_COUNTER = _CountingGenerator(_gen_mod.get_generator())
_gen_mod._GENERATOR = _LLM_COUNTER


class JudgeOnlySystem:
    """只做【检索 + 判定】的系统（跳过生成），用于 max_check 消融。

    与 QAPipeline 的唯一差异在最后一步：不调用 generator.answer()，
    answer 恒为空字符串、timing["generate"] 恒为 0.0；
    阈值初筛、逐块判定、拒答语义均与 b3_full 保持一致。
    """

    def __init__(self, max_check: int, top_k: int, name: str):
        self.retriever = get_retriever()
        self.max_check = max_check
        self.top_k = top_k
        self.name = name
        self.judge_ms = []

    def __call__(self, question: str) -> dict:
        t0 = time.perf_counter()
        hits = self.retriever.retrieve(question, top_k=self.top_k)
        t_ret = time.perf_counter() - t0

        t1 = time.perf_counter()
        judge = self.retriever.is_answerable(question, hits, max_check=self.max_check)
        t_judge = time.perf_counter() - t1
        self.judge_ms.append(round(t_judge * 1000, 1))

        refused = not judge["answerable"]
        return {
            "answer": "",                       # ★ 不生成
            "refused": refused,
            "sources": [],                      # 无生成则无引用（citation 恒为 0）
            "retrieved": [{"chunk_id": h["chunk_id"], "doc_id": h["doc_id"]} for h in hits],
            "timing": {"retrieve": round(t_ret, 3), "judge": round(t_judge, 3),
                       "generate": 0.0, "total": round(t_ret + t_judge, 3)},
        }


def stratified_sample(split: str, n_total: int, seed: int = 42) -> list:
    """按 category 分层抽样（配额按比例分配；种子固定 42，可复现）。"""
    rows = load_questions(split)
    by_cat = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r["qid"])

    rng = random.Random(seed)
    picked = []
    for cat, quota in PILOT_QUOTA.items():
        pool = sorted(by_cat.get(cat, []))
        rng.shuffle(pool)
        picked.extend(pool[:quota])
    rest = [q for q in sorted(r["qid"] for r in rows) if q not in picked]
    rng.shuffle(rest)
    picked.extend(rest[:max(0, n_total - len(picked))])
    return picked[:n_total]


def main():
    ap = argparse.ArgumentParser(description="max_check 消融实验（三档正交，只跑 dev）")
    ap.add_argument("--configs", default=",".join(CONFIG_ORDER),
                    help="要跑的档位，逗号分隔")
    ap.add_argument("--split", default="dev")
    ap.add_argument("--limit", type=int, default=None,
                    help="只跑 N 题（按 category 分层抽样，种子 42）；不传则全量 61 题")
    ap.add_argument("--out-csv", default=None, help="默认追加 eval/data/eval_runs.csv")
    args = ap.parse_args()

    assert args.split == "dev", "★ 本批只允许 split=dev（test 集冻结）"

    qids = None
    if args.limit:
        qids = stratified_sample(args.split, args.limit, seed=42)
        print(f"先导抽样 {len(qids)} 题（分层，种子 42）: {qids}")

    for name in [c.strip() for c in args.configs.split(",") if c.strip()]:
        cfg = CONFIGS[name]
        print("\n" + "#" * 92)
        print(f"# {name}   recall top_k={cfg['top_k']}   max_check={cfg['max_check']}   （只检索+判定）")
        print("#" * 92)
        sys_obj = JudgeOnlySystem(cfg["max_check"], cfg["top_k"], name)
        before = _LLM_COUNTER.calls
        t0 = time.perf_counter()
        run_eval(sys_obj, split=args.split, out_csv=args.out_csv, qids=qids)
        dt = time.perf_counter() - t0
        jm = sys_obj.judge_ms
        if jm:
            print(f"\n[{name}] 完成，总耗时 {dt:.1f}s   "
                  f"判定耗时: 平均 {sum(jm) / len(jm):.0f}ms  最大 {max(jm):.0f}ms  (n={len(jm)})")
        print(f"[{name}] 本档 LLM 调用 {_LLM_COUNTER.calls - before} 次  "
              f"（累计 {_LLM_COUNTER.calls}）")


if __name__ == "__main__":
    main()
