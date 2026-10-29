"""analyze_e3_rerank_detail.py — E3 专项分析②③（只跑检索+重排，不调 LLM）

② 答案块排名提升幅度：统计 gold 块在重排前后的名次（recall_rank vs rerank_rank）
③ 排序稳定性：原问法 vs 去标点问法，比较 top-5 序列一致率（无重排 / 有重排）

去标点构造与 eval/exp_punct_sensitivity.md 一致（去首尾 ？?。.！!，,、；;：:…～~ 与空白）。

用法：python scripts/analyze_e3_rerank_detail.py
"""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根入 path

import config  # noqa: E402
from src.retriever import Retriever  # noqa: E402

PUNCT = "？?。.！!，,、；;：:…～~ \t\r\n"


def strip_punct(s: str) -> str:
    return s.strip(PUNCT)


def _gold_rank(hits: list, gold: set):
    for i, it in enumerate(hits, start=1):
        if it["chunk_id"] in gold:
            return i
    return None


def main():
    rows = list(csv.DictReader(open(config.EVAL_DATA_DIR / "questions.csv", encoding="utf-8-sig")))
    dev = [r for r in rows if r["split"] == "dev"]

    r_no = Retriever(use_rerank=False)
    r_yes = Retriever(use_rerank=True)

    # ---------------- ② gold 块排名提升 ----------------
    print("=" * 100)
    print("② gold 块排名提升（召回 top-20 → 重排）")
    print("=" * 100)
    details = []
    for q in dev:
        gold = {x for x in q["gold_chunk_ids"].split("|") if x}
        if not gold:
            continue
        rec = r_no.retrieve(q["question"], top_k=20)
        _ = r_yes.retrieve(q["question"], top_k=20)
        reranked_all = r_yes.last_reranked_all or []
        rr_recall = _gold_rank(rec, gold)          # 重排前（同一批 20 个候选）
        rr_after = _gold_rank(reranked_all, gold)  # 重排后
        details.append({"qid": q["qid"], "category": q["category"],
                        "recall_rank": rr_recall, "rerank_rank": rr_after,
                        "n_gold": len(gold)})

    have = [d for d in details if d["recall_rank"] and d["rerank_rank"]]
    avg_before = sum(d["recall_rank"] for d in have) / len(have)
    avg_after = sum(d["rerank_rank"] for d in have) / len(have)
    improved = [d for d in have if d["rerank_rank"] < d["recall_rank"]]
    worsened = [d for d in have if d["rerank_rank"] > d["recall_rank"]]
    top3_before = [d for d in have if d["recall_rank"] <= 3]
    top3_after = [d for d in have if d["rerank_rank"] <= 3]

    print(f"参与统计（有 gold 且在 top-20 内）: {len(have)} 题")
    print(f"  gold 平均名次: 重排前 {avg_before:.2f}  →  重排后 {avg_after:.2f}  "
          f"（变化 {avg_after - avg_before:+.2f}）")
    print(f"  被【提前】的题数: {len(improved)}")
    print(f"  被【推后】的题数: {len(worsened)}")
    print(f"  名次不变: {len(have) - len(improved) - len(worsened)}")
    print(f"  gold 落入 top-3: 重排前 {len(top3_before)}  →  重排后 {len(top3_after)}")

    print(f"\n  {'qid':<7}{'category':<11}{'重排前':>8}{'重排后':>8}  变化")
    print("  " + "-" * 60)
    for d in sorted(details, key=lambda x: (x["qid"])):
        b = d["recall_rank"]
        a = d["rerank_rank"]
        if b is None or a is None:
            mark = "（gold 不在 top-20）"
            print(f"  {d['qid']:<7}{d['category']:<11}{str(b):>8}{str(a):>8}  {mark}")
            continue
        delta = a - b
        mark = "★提前" if delta < 0 else ("推后" if delta > 0 else "不变")
        print(f"  {d['qid']:<7}{d['category']:<11}{b:>8}{a:>8}  {mark} ({delta:+d})")

    pdf = config.EVAL_DATA_DIR / "exp_e3_rerank_rank.json"
    pdf.write_text(json.dumps(
        {"n": len(have), "avg_recall_rank": round(avg_before, 4),
         "avg_rerank_rank": round(avg_after, 4), "improved": len(improved),
         "worsened": len(worsened), "top3_before": len(top3_before),
         "top3_after": len(top3_after), "details": details},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  已落盘 {pdf}")

    # ---------------- ③ 排序稳定性 ----------------
    print("\n" + "=" * 100)
    print("③ 排序稳定性：原问法 vs 去标点问法（top-5 序列一致率）")
    print("=" * 100)
    n = 0
    exact_no = exact_yes = set_no = set_yes = 0
    rank1_change_no = rank1_change_yes = 0
    for q in dev:
        qa, qb = q["question"], strip_punct(q["question"])
        n += 1
        a = [it["chunk_id"] for it in r_no.retrieve(qa, top_k=5)]
        b = [it["chunk_id"] for it in r_no.retrieve(qb, top_k=5)]
        if a == b:
            exact_no += 1
        if set(a) == set(b):
            set_no += 1
        if a and b and a[0] != b[0]:
            rank1_change_no += 1

        ar = [it["chunk_id"] for it in r_yes.retrieve(qa, top_k=5)]
        br = [it["chunk_id"] for it in r_yes.retrieve(qb, top_k=5)]
        if ar == br:
            exact_yes += 1
        if set(ar) == set(br):
            set_yes += 1
        if ar and br and ar[0] != br[0]:
            rank1_change_yes += 1

    print(f"题数: {n}")
    print(f"{'指标':<32}{'无重排':>14}{'有重排':>14}")
    print("-" * 100)
    print(f"{'top-5 序列完全一致':<32}{exact_no:>10}/{n}{exact_yes:>10}/{n}")
    print(f"{'top-5 集合一致':<32}{set_no:>10}/{n}{set_yes:>10}/{n}")
    print(f"{'top-1 发生变化':<32}{rank1_change_no:>10}/{n}{rank1_change_yes:>10}/{n}")
    print(f"{'一致率（序列）':<32}{exact_no / n:>14.3f}{exact_yes / n:>14.3f}")
    print(f"{'一致率（集合）':<32}{set_no / n:>14.3f}{set_yes / n:>14.3f}")

    pdf2 = config.EVAL_DATA_DIR / "exp_e3_stability.json"
    pdf2.write_text(json.dumps({
        "n": n, "exact_same_no_rerank": exact_no, "exact_same_rerank": exact_yes,
        "set_same_no_rerank": set_no, "set_same_rerank": set_yes,
        "rank1_change_no_rerank": rank1_change_no, "rank1_change_rerank": rank1_change_yes,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已落盘 {pdf2}")


if __name__ == "__main__":
    main()
