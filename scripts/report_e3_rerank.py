"""report_e3_rerank.py — E3 重排消融结果汇总（★纯计算，不加载任何模型）

从 eval/data/eval_runs.csv 复算 b3_full / b3_rerank / b3_rerank_top10 的对比，
并回答 Q1~Q4、列出 15 道过度拒答题在重排后的变化、单独报告 cross 类指标。

用法：python scripts/report_e3_rerank.py
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根入 path

import config  # noqa: E402
from src import eval_metrics  # noqa: E402

OVER_REFUSAL_QIDS = ["q016", "q018", "q020", "q021", "q028", "q029", "q030", "q041",
                     "q045", "q048", "q051", "q063", "q076", "q078", "q080"]
SYSTEMS = ["b3_full", "b3_rerank", "b3_rerank_top10"]


def _latest(rows: list, name: str):
    sub = [r for r in rows if r["system"] == name]
    if not sub:
        return None, []
    last = sub[-1]["run_id"]
    return last, [r for r in sub if r["run_id"] == last]


def _mean(vals):
    nums = []
    for v in vals:
        try:
            nums.append(float(v))
        except (TypeError, ValueError):
            continue
    return round(sum(nums) / len(nums), 4) if nums else 0.0


def _metrics(rows: list, cat=None) -> dict:
    sub = [r for r in rows if (cat is None or r["category"] == cat)]
    if not sub:
        return {}
    m = eval_metrics.refuse_binary_metrics(
        [{"refused": r["refused"], "answerable": r["answerable_gt"]} for r in sub])
    m["recall@1"] = _mean([r["recall@1"] for r in sub])
    m["recall@3"] = _mean([r["recall@3"] for r in sub])
    m["recall@5"] = _mean([r["recall@5"] for r in sub])
    m["recall@10"] = _mean([r["recall@10"] for r in sub])
    m["mrr"] = _mean([r["mrr"] for r in sub])
    m["doc_hit@5"] = _mean([1 if r["gold_doc_hit"] == "true" else 0 for r in sub])
    m["cite_avg"] = _mean([r["citation_total"] for r in sub])
    m["retrieve_ms"] = _mean([r["retrieve_ms"] for r in sub])
    m["judge_ms"] = _mean([r["judge_ms"] for r in sub])
    m["generate_ms"] = _mean([r["generate_ms"] for r in sub])
    m["total_ms"] = _mean([r["total_ms"] for r in sub])
    return m


ROWS = [("Recall@1", "recall@1"), ("Recall@3", "recall@3"), ("Recall@5", "recall@5"),
        ("Recall@10", "recall@10"), ("MRR", "mrr"), ("gold_doc_hit@5", "doc_hit@5"),
        ("拒答查准率 P", "precision"), ("拒答查全率 R", "recall"), ("拒答 F1", "f1"),
        ("可答侧放行率", "pass_rate_on_answerable"),
        ("总体正确率*", "overall_accuracy"),
        ("tp", "tp"), ("fp", "fp"), ("fn", "fn"), ("tn", "tn"),
        ("平均引用数", "cite_avg"),
        ("检索ms", "retrieve_ms"), ("判定ms", "judge_ms"),
        ("生成ms", "generate_ms"), ("总ms", "total_ms")]


def main():
    rows = list(csv.DictReader(open(config.EVAL_RUNS_CSV, encoding="utf-8-sig")))
    rows = [r for r in rows if not r["error"]]

    data = {}
    for s in SYSTEMS:
        run_id, sub = _latest(rows, s)
        if sub:
            data[s] = (run_id, sub)
    names = list(data)

    print("=" * 108)
    print("E3 重排消融：三档对比（dev 集，纯计算复算）")
    print("=" * 108)
    for n in names:
        print(f"  {n:<18} run_id={data[n][0]}  n={len(data[n][1])}")
    print("-" * 108)
    print(f"{'指标':<18}" + "".join(f"{n:>24}" for n in names))
    print("-" * 108)
    agg = {n: _metrics(data[n][1]) for n in names}
    for label, key in ROWS:
        cells = []
        for n in names:
            v = agg[n].get(key, 0)
            cells.append(f"{v:>24.3f}" if isinstance(v, float) else f"{v:>24}")
        print(f"{label:<18}" + "".join(cells))
    print("-" * 108)
    print("* 总体正确率受类别不平衡影响（应拒答仅 4/61），仅供参考")

    # ---- Q2：15 道过度拒答题在重排后的变化 ----
    print("\n" + "=" * 108)
    print("Q2/E①：15 道过度拒答题在 b3_rerank 下的变化")
    print("=" * 108)
    if "b3_full" in data and "b3_rerank" in data:
        full = {r["qid"]: r for r in data["b3_full"][1]}
        rrk = {r["qid"]: r for r in data["b3_rerank"][1]}
        print(f"{'qid':<7}{'category':<11}{'b3_full':>10}{'b3_rerank':>12}  变化")
        print("-" * 108)
        fixed = 0
        still = 0
        for qid in OVER_REFUSAL_QIDS:
            a = full.get(qid)
            b = rrk.get(qid)
            if not a or not b:
                print(f"{qid:<7}{'—':<11}{'—':>10}{'—':>12}  （缺记录）")
                continue
            a_r = "拒答" if a["refused"] == "true" else "放行"
            b_r = "拒答" if b["refused"] == "true" else "放行"
            if a_r == "拒答" and b_r == "放行":
                mark = "★ 恢复为可回答"
                fixed += 1
            elif b_r == "拒答":
                mark = "仍拒答"
                still += 1
            else:
                mark = "（原已放行）"
            print(f"{qid:<7}{a['category']:<11}{a_r:>10}{b_r:>12}  {mark}")
        print("-" * 108)
        print(f"恢复为可回答: {fixed}/15    仍拒答: {still}/15")

        # 反向：原本放行、重排后变拒答
        back = [q for q in full if full[q]["refused"] == "false" and rrk.get(q, {}).get("refused") == "true"]
        print(f"\n反向变化（b3_full 放行 → b3_rerank 拒答）: {len(back)} 题")
        for q in back:
            print(f"  {q} [{full[q]['category']}] {full[q]['question'][:34]}")

    # ---- Q3/G：cross 类单独指标 ----
    print("\n" + "=" * 108)
    print("G：cross（跨文档）类单独指标")
    print("=" * 108)
    print(f"{'指标':<18}" + "".join(f"{n:>24}" for n in names))
    print("-" * 108)
    cross = {n: _metrics(data[n][1], "cross") for n in names}
    for label, key in ROWS[:11]:
        cells = []
        for n in names:
            v = cross[n].get(key, 0)
            cells.append(f"{v:>24.3f}" if isinstance(v, float) else f"{v:>24}")
        print(f"{label:<18}" + "".join(cells))

    # ---- 分 category 的过拒数 ----
    print("\n" + "=" * 108)
    print("按 category 的过度拒答数 / 拒答查全率")
    print("=" * 108)
    print(f"{'category':<12}{'指标':<14}" + "".join(f"{n:>24}" for n in names))
    print("-" * 108)
    for cat in ["fact", "procedure", "cross", "refuse"]:
        for label, key in [("过拒数", "fp"), ("拒答查全率 R", "recall"), ("可答侧放行率", "pass_rate_on_answerable")]:
            cells = []
            for n in names:
                m = _metrics(data[n][1], cat)
                v = m.get(key, 0)
                cells.append(f"{v:>24.3f}" if isinstance(v, float) else f"{v:>24}")
            print(f"{cat:<12}{label:<14}" + "".join(cells))


if __name__ == "__main__":
    main()
