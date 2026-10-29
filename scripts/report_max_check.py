"""report_max_check.py — max_check 消融结果汇总（★纯计算，不加载任何模型）

从 eval/data/eval_runs.csv 复算 b3_mc3_r5 / b3_mc3_r10 / b3_mc8_r10 三档对比，
并回答 Q1~Q3、产出四项专项分析（15 道过拒题恢复情况 / 新增过拒 /
gold 排名分布 vs max_check / 耗时代价）。

用法：python scripts/report_max_check.py
"""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根入 path

import config  # noqa: E402
from src import eval_metrics  # noqa: E402

OVER_REFUSAL_QIDS = ["q016", "q018", "q020", "q021", "q028", "q029", "q030", "q041",
                     "q045", "q048", "q051", "q063", "q076", "q078", "q080"]
PILOT_HARD = ["q020", "q029", "q041", "q063"]   # 先导就暴露的 4 道"多看块也救不回"
SYSTEMS = ["b3_mc3_r5", "b3_mc3_r10", "b3_mc8_r10", "b3_full"]


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


def _metrics(rows: list) -> dict:
    if not rows:
        return {}
    m = eval_metrics.refuse_binary_metrics(
        [{"refused": r["refused"], "answerable": r["answerable_gt"]} for r in rows])
    for k, col in [("recall@1", "recall@1"), ("recall@3", "recall@3"),
                   ("recall@5", "recall@5"), ("recall@10", "recall@10"), ("mrr", "mrr")]:
        m[k] = _mean([r[col] for r in rows])
    m["doc_hit@5"] = _mean([1 if r["gold_doc_hit"] == "true" else 0 for r in rows])
    for k, col in [("retrieve_ms", "retrieve_ms"), ("judge_ms", "judge_ms"),
                   ("generate_ms", "generate_ms"), ("total_ms", "total_ms")]:
        m[k] = _mean([r[col] for r in rows])
    return m


ROWS = [("Recall@1", "recall@1"), ("Recall@3", "recall@3"), ("Recall@5", "recall@5"),
        ("Recall@10", "recall@10"), ("MRR", "mrr"), ("gold_doc_hit@5", "doc_hit@5"),
        ("★拒答查准率 P", "precision"), ("★拒答查全率 R", "recall"), ("★F1", "f1"),
        ("可答侧放行率", "pass_rate_on_answerable"),
        ("总体正确率*", "overall_accuracy"),
        ("tp(正确拒答)", "tp"), ("fp(过度拒答)", "fp"),
        ("fn(该拒不拒)", "fn"), ("tn(正确放行)", "tn"),
        ("检索 ms", "retrieve_ms"), ("判定 ms", "judge_ms"),
        ("生成 ms", "generate_ms"), ("总 ms", "total_ms")]


def main():
    rows = [r for r in csv.DictReader(open(config.EVAL_RUNS_CSV, encoding="utf-8-sig"))
            if not r["error"]]

    data, run_ids = {}, {}
    for s in SYSTEMS:
        rid, sub = _latest(rows, s)
        if sub:
            data[s] = sub
            run_ids[s] = rid
    names = [s for s in SYSTEMS if s in data]

    print("=" * 112)
    print("max_check 消融：三档正交对比（dev 61 题，纯计算复算）")
    print("=" * 112)
    for n in names:
        print(f"  {n:<14} run_id={run_ids[n]}  n={len(data[n])}")
    print("-" * 112)
    print(f"{'指标':<18}" + "".join(f"{n:>19}" for n in names))
    print("-" * 112)
    agg = {n: _metrics(data[n]) for n in names}
    for label, key in ROWS:
        cells = []
        for n in names:
            v = agg[n].get(key, 0)
            cells.append(f"{v:>19.3f}" if isinstance(v, float) else f"{v:>19}")
        print(f"{label:<18}" + "".join(cells))
    print("-" * 112)
    print("* 总体正确率受类别不平衡影响（应拒答仅 4/61），仅供参考")

    # ---- 专项一：15 道过拒题在各档的恢复情况 ----
    print("\n" + "=" * 112)
    print("专项一：15 道过度拒答题在 b3_mc3_r5 / b3_mc3_r10 / b3_mc8_r10 下的变化")
    print("=" * 112)
    cols = [n for n in names if n != "b3_full"]
    by_s = {n: {r["qid"]: r for r in data[n]} for n in names}
    print(f"{'qid':<7}{'category':<11}" + "".join(f"{n:>16}" for n in cols) + "   变化")
    print("-" * 112)
    recover = {n: [] for n in cols}
    for qid in OVER_REFUSAL_QIDS:
        cells, marks = [], []
        for n in cols:
            r = by_s[n].get(qid)
            if not r:
                cells.append(f"{'—':>16}")
                continue
            ref = "拒答" if r["refused"] == "true" else "放行"
            cells.append(f"{ref:>16}")
            if ref == "放行":
                recover[n].append(qid)
                marks.append(f"{n.split('_')[1]}恢复")
        mark = ("★ " + "、".join(marks)) if marks else "三档均拒答"
        cat = by_s[cols[0]].get(qid, {}).get("category", "-")
        print(f"{qid:<7}{cat:<11}" + "".join(cells) + f"   {mark}")
    print("-" * 112)
    for n in cols:
        print(f"  {n:<14} 恢复为可回答: {len(recover[n])}/15  {recover[n]}")

    # ---- 专项一b：先导 4 道难题的三档确认 ----
    print("\n" + "=" * 112)
    print("专项一b：先导 4 道'多看块也救不回'的题在全量三档下的确认")
    print("=" * 112)
    print(f"{'qid':<7}{'category':<11}" + "".join(f"{n:>16}" for n in cols) + "   判定耗时(ms)")
    print("-" * 112)
    all_refused = []
    for qid in PILOT_HARD:
        cells = []
        jm = []
        for n in cols:
            r = by_s[n].get(qid)
            if not r:
                cells.append(f"{'—':>16}")
                continue
            cells.append(f"{('拒答' if r['refused'] == 'true' else '放行'):>16}")
            jm.append(r["judge_ms"])
        refused_all = all(by_s[n].get(qid, {}).get("refused") == "true" for n in cols)
        if refused_all:
            all_refused.append(qid)
        cat = by_s[cols[0]].get(qid, {}).get("category", "-")
        print(f"{qid:<7}{cat:<11}" + "".join(cells) + f"   {' / '.join(jm)}")
    print("-" * 112)
    print(f"三档【全部拒答】的题: {len(all_refused)}/{len(PILOT_HARD)}  {all_refused}")
    if len(all_refused) == len(PILOT_HARD):
        print("★ 结论：这些题的失败与判定窗口大小【无关】，属判定器本身的错误判定。")

    # ---- 专项二：新增过度拒答 ----
    print("\n" + "=" * 112)
    print("专项二：是否引入新的过度拒答（相对基线 b3_mc3_r5）")
    print("=" * 112)
    base = by_s.get("b3_mc3_r5", {})
    for n in cols:
        if n == "b3_mc3_r5":
            continue
        cur = by_s[n]
        new_bad = [q for q in base if base[q]["refused"] == "false"
                   and cur.get(q, {}).get("refused") == "true"]
        fixed = [q for q in base if base[q]["refused"] == "true"
                 and cur.get(q, {}).get("refused") == "false"]
        print(f"\n  {n} vs b3_mc3_r5:")
        print(f"    新增过拒（放行→拒答）: {len(new_bad)} 题 {new_bad}")
        print(f"    恢复（拒答→放行）    : {len(fixed)} 题 {fixed}")
        print(f"    净变化: {len(fixed) - len(new_bad):+d} 题")

    # ---- 专项三：gold 块排名分布 vs max_check ----
    print("\n" + "=" * 112)
    print("专项三：gold 块排名分布 vs max_check（理论上每档'能看到'多少题的 gold 块）")
    print("=" * 112)
    rca_path = config.EVAL_DATA_DIR / "rca_over_refusal.json"
    if rca_path.exists():
        rca = json.loads(rca_path.read_text(encoding="utf-8"))
        items = rca.get("results", []) if isinstance(rca, dict) else rca
        ranks = {}
        for it in items:
            gold = set(it.get("gold_chunk_ids", []) or [])
            g = None
            for h in it.get("retrieved", []):
                if h.get("chunk_id") in gold:
                    g = h.get("rank")
                    break
            if g:
                ranks[it["qid"]] = g
        dist = {}
        for g in ranks.values():
            dist[g] = dist.get(g, 0) + 1
        print(f"  15 道过拒题的 gold 块排名分布: {dict(sorted(dist.items()))}")
        for mc in [3, 5, 8]:
            seen = sum(1 for g in ranks.values() if g <= mc)
            print(f"  max_check={mc}: 判定器'能看到' gold 块的题数 = {seen}/15"
                  f"（排名 ≤ {mc}）")
            if mc == 3:
                print(f"      → 排名 > 3 的题: "
                      f"{sorted([q for q, g in ranks.items() if g > 3])}")
        print("\n  ★ 实测对照：")
        for n in cols:
            fp = agg[n].get("fp", 0)
            print(f"    {n:<14} 实际过度拒答 {fp} 题")
    else:
        print("  （未找到 eval/data/rca_over_refusal.json，跳过）")

    # ---- 专项四：耗时代价 ----
    print("\n" + "=" * 112)
    print("专项四：耗时代价")
    print("=" * 112)
    print(f"{'档位':<14}{'判定均耗时ms':>14}{'判定总耗时s':>14}{'判定次数估算':>14}"
          f"{'过拒数':>8}{'相对基线':>10}")
    print("-" * 112)
    base_fp = agg.get("b3_mc3_r5", {}).get("fp", 0)
    base_j = agg.get("b3_mc3_r5", {}).get("judge_ms", 0)
    for n in cols:
        m = agg[n]
        jm = m.get("judge_ms", 0)
        tot = jm * m.get("n", 0) / 1000
        est = round(tot / 2.12)   # 单块判定约 2.1s
        print(f"{n:<14}{jm:>14.1f}{tot:>14.1f}{est:>14}{m.get('fp', 0):>8}"
              f"{jm - base_j:>+10.1f}")
    print("-" * 112)
    print(f"  单块判定实测约 2.1s（先导日志：每次逐块判定 2.1s）")
    print(f"  判定耗时随 max_check 的增长不成线性：早停/阈值题不进判定，只有 NO 题跑满窗口")
    print("\n  权衡（每多救回 1 题需增加多少判定耗时）：")
    for n in cols:
        if n == "b3_mc3_r5":
            continue
        saved = base_fp - agg[n].get("fp", 0)
        extra_s = (agg[n]["judge_ms"] - base_j) * agg[n]["n"] / 1000
        if saved > 0:
            print(f"    {n}: 救回 {saved} 题，多花 {extra_s:.1f}s → "
                  f"每救回 1 题 {extra_s / saved:.1f}s")
        else:
            print(f"    {n}: 救回 {saved} 题（无改善），却多花 {extra_s:.1f}s → 纯负收益")


if __name__ == "__main__":
    main()
