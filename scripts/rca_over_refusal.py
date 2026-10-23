"""rca_over_refusal.py — B3 过度拒答 15 题的归因分析（root cause analysis）

只跑 b3_full 的 15 道过度拒答题；★只做「检索 + 判定」，跳过生成回答。

verdict 判定规则（写死在 _verdict() 中）：
  retrieval_miss：top-10 中【不含】任何 gold_chunk_id（检索没找到）
  judge_reject  ：top-10 中含 gold_chunk_id，但最终仍拒答（找到了却判 NO）
  unknown       ：该题 gold_chunk_ids 为空（无法判定）

★ 结果落盘 eval/data/rca_over_refusal.json，【不写】eval/data/eval_runs.csv（避免污染基线数据）。
★ LLM 调用预算 16 次（本批纪律）；预算用尽时该题 judge 标记 budget_exhausted，
  verdict 仍按"gold 是否命中"判定（refused=true 已由 eval_runs.csv 记录）。

用法：python scripts/rca_over_refusal.py
"""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根入 path

import config  # noqa: E402
from src.retriever import get_retriever  # noqa: E402
from src.generator import get_generator  # noqa: E402

QIDS = ["q016", "q018", "q020", "q021", "q028", "q029", "q030", "q041",
        "q045", "q048", "q051", "q063", "q076", "q078", "q080"]
LLM_BUDGET = 16          # 本批纪律：LLM 调用总次数上限
EARLY_STOP = 0.62        # retriever.verify_answerable 的早停阈值
OUT_JSON = config.EVAL_DATA_DIR / "rca_over_refusal.json"


def _split_ids(s: str) -> list:
    return [x for x in (s or "").split("|") if x]


class _CountingGenerator:
    """包装 generator，统计 LLM 调用次数并在超出预算时熔断。"""

    def __init__(self, inner, budget: int):
        self._inner = inner
        self.budget = budget
        self.calls = 0

    def chat(self, *a, **k):
        if self.calls >= self.budget:
            raise RuntimeError(f"LLM 调用预算已用尽（{self.budget} 次）")
        self.calls += 1
        return self._inner.chat(*a, **k)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _verdict(gold_chunks: list, hits: list) -> str:
    """按规则给出归因分类。"""
    if not gold_chunks:
        return "unknown"
    gold = set(gold_chunks)
    retrieved_ids = [h["chunk_id"] for h in hits]
    if not (gold & set(retrieved_ids)):
        return "retrieval_miss"
    return "judge_reject"


def _gold_rank(gold_chunks: list, hits: list):
    """gold 块在检索结果中的最高排名（1-based），未命中返回 None。"""
    gold = set(gold_chunks)
    for h in hits:
        if h["chunk_id"] in gold:
            return h["rank"] + 1
    return None


def main():
    rows = list(csv.DictReader(open(config.EVAL_DATA_DIR / "questions.csv", encoding="utf-8-sig")))
    qmap = {r["qid"]: r for r in rows}

    # 注入计数包装（retriever.verify_answerable 内部会取 generator 单例）
    from src import generator as gen_mod
    counter = _CountingGenerator(get_generator(), LLM_BUDGET)
    gen_mod._GENERATOR = counter

    retriever = get_retriever()

    # ---- 阶段1：全部检索（不调 LLM）----
    hits_by_qid = {}
    for qid in QIDS:
        q = qmap[qid]
        hits_by_qid[qid] = retriever.retrieve(q["question"], top_k=10)

    print("=" * 100)
    print("阶段1：检索（top-10，无 LLM 调用）")
    print("=" * 100)
    need_llm = 0
    for qid in QIDS:
        h = hits_by_qid[qid]
        r1 = h[0]["score"] if h else 0.0
        est = 3 if (h and config.SCORE_THRESHOLD <= r1 < EARLY_STOP) else 0
        need_llm += est
        print(f"  {qid}  rank1={r1:.4f}  预估LLM={est}  "
              f"gold命中={'是' if _gold_rank(_split_ids(qmap[qid]['gold_chunk_ids']), h) else '否'}")
    print(f"\n预估 LLM 调用总数（上界）: {need_llm}  预算: {LLM_BUDGET}")

    # ---- 阶段2：判定（受预算约束）----
    print("\n" + "=" * 100)
    print("阶段2：判定 is_answerable()（受 LLM 预算约束）")
    print("=" * 100)
    results = []
    for qid in QIDS:
        q = qmap[qid]
        hits = hits_by_qid[qid]
        gold_chunks = _split_ids(q["gold_chunk_ids"])
        gold_docs = _split_ids(q["source_docs"])
        r1 = hits[0]["score"] if hits else 0.0
        will_need = bool(hits) and config.SCORE_THRESHOLD <= r1 < EARLY_STOP

        if will_need and counter.calls + 3 > LLM_BUDGET:
            judge = {"answerable": None, "stage": "budget_exhausted",
                     "reason": f"LLM 预算不足（已用 {counter.calls}/{LLM_BUDGET}），未重新判定；"
                               f"该题在 eval_runs.csv 中 refused=true",
                     "chunks_checked": 0, "yes_chunk_id": ""}
            print(f"  {qid}: 跳过判定（预算不足）")
        else:
            judge = retriever.is_answerable(q["question"], hits)
            judge = {"answerable": judge["answerable"], "stage": judge["stage"],
                     "reason": judge["reason"][:200], "chunks_checked": judge["chunks_checked"],
                     "yes_chunk_id": judge["yes_chunk_id"]}

        verdict = _verdict(gold_chunks, hits)
        results.append({
            "qid": qid,
            "question": q["question"],
            "category": q["category"],
            "gold_chunk_ids": gold_chunks,
            "gold_doc_ids": gold_docs,
            "gold_answer": q["gold_answer"],
            "retrieved": [{"rank": h["rank"] + 1, "chunk_id": h["chunk_id"],
                           "doc_id": h["doc_id"], "score": round(h["score"], 4),
                           "heading_path": h["heading_path"]} for h in hits],
            "gold_rank": _gold_rank(gold_chunks, hits),
            "judge": judge,
            "verdict": verdict,
        })
        print(f"  {qid}: verdict={verdict}  gold_rank={_gold_rank(gold_chunks, hits)}  "
              f"stage={judge['stage']}  (LLM 累计 {counter.calls})")

    OUT_JSON.write_text(json.dumps(
        {"llm_calls_used": counter.calls, "llm_budget": LLM_BUDGET,
         "n_questions": len(QIDS), "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"\n已落盘 {OUT_JSON}（LLM 实际调用 {counter.calls} 次）")

    # ---- 汇总 ----
    print("\n" + "=" * 100)
    print("归因汇总")
    print("=" * 100)
    print(f"{'qid':<7}{'category':<11}{'verdict':<15}{'gold_rank':>10}{'rank1':>9}  问题")
    print("-" * 100)
    for r in results:
        r1 = r["retrieved"][0]["score"] if r["retrieved"] else 0.0
        print(f"{r['qid']:<7}{r['category']:<11}{r['verdict']:<15}"
              f"{str(r['gold_rank']):>10}{r1:>9.4f}  {r['question'][:30]}")

    from collections import Counter
    vc = Counter(r["verdict"] for r in results)
    print(f"\nverdict 统计: {dict(vc)}")
    cross = Counter((r["verdict"], r["category"]) for r in results)
    for cat in ["fact", "procedure", "cross"]:
        n = Counter(r["verdict"] for r in results if r["category"] == cat)
        print(f"  {cat:<10}: {dict(n)}")

    print("\n--- retrieval_miss 题的 top-3 实检索内容 ---")
    for r in results:
        if r["verdict"] != "retrieval_miss":
            continue
        print(f"  [{r['qid']}] {r['question'][:36]}  (gold_doc={r['gold_doc_ids']})")
        for h in r["retrieved"][:3]:
            print(f"      #{h['rank']} {h['chunk_id']:<22} {h['score']:.4f}  {h['heading_path'][:38]}")

    print("\n--- judge_reject 题的 gold 排名 ---")
    for r in results:
        if r["verdict"] != "judge_reject":
            continue
        print(f"  [{r['qid']}] gold_rank={r['gold_rank']}  stage={r['judge']['stage']}  "
              f"checked={r['judge']['chunks_checked']}  {r['question'][:32]}")


if __name__ == "__main__":
    main()
