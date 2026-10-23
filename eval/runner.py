"""runner.py — 评测运行器

对给定基线（system）与给定 split 逐题跑完并汇总指标。

用法：
    import sys; sys.path.insert(0, r"D:\\campus-rag")
    from eval.runner import run_eval
    run_eval(my_system, split="dev")

system 契约：可调用对象，签名 system(question) -> dict，返回
    {"answer": str, "refused": bool, "sources": list,
     "retrieved": list, "timing": dict}
其中 retrieved 为按 rank 排序的检索块列表（元素含 chunk_id / doc_id）。

★ 追加写：eval/data/eval_runs.csv 已存在则追加，绝不覆盖（保护历史实验）。
★ 单题失败：error 字段记录异常，其余指标留空，继续跑下一题。
"""
import csv
import sys
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根入 path

import config  # noqa: E402
from src import eval_metrics  # noqa: E402

HEADER = [
    "run_id", "timestamp", "system", "split", "qid", "category",
    "question", "answer", "refused", "answerable_gt",
    "recall@1", "recall@3", "recall@5", "recall@10",
    "hit@5", "mrr", "gold_doc_hit",
    "refused_correct", "citation_total", "citation_valid",
    "retrieve_ms", "judge_ms", "generate_ms", "total_ms",
    "error",
]


def load_questions(split: str = "dev") -> list:
    """读评估集并过滤 split（questions.csv 只读，不修改）。"""
    with open(config.EVAL_DATA_DIR / "questions.csv", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if r["split"] == split]


def _split_ids(s: str) -> list:
    return [x for x in (s or "").split("|") if x]


def _system_name(system) -> str:
    return getattr(system, "name", None) or getattr(system, "__name__", "system")


def run_eval(system, split: str = "dev", out_csv=None, limit=None, qids=None) -> dict:
    """逐题评测并汇总。返回汇总指标 dict。

    qids：可选，只评测指定 qid 列表（用于分层抽样的先导测试）；None 表示全部。
    """
    questions = load_questions(split)
    if qids:
        qset = set(qids)
        questions = [q for q in questions if q["qid"] in qset]
    if limit:
        questions = questions[:limit]

    name = _system_name(system)
    ts = datetime.now()
    run_id = f"{ts.strftime('%Y%m%d_%H%M')}_{split}_{name}"
    out_csv = Path(out_csv) if out_csv else config.EVAL_RUNS_CSV
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    records = []
    for q in questions:
        rec = {k: "" for k in HEADER}
        rec.update({
            "run_id": run_id, "timestamp": ts.isoformat(timespec="seconds"),
            "system": name, "split": split, "qid": q["qid"],
            "category": q["category"], "question": q["question"],
            "answerable_gt": q["answerable"].strip().lower(),
        })
        try:
            res = system(q["question"])
            rec["answer"] = res.get("answer", "")
            rec["refused"] = str(bool(res.get("refused", False))).lower()

            retrieved = res.get("retrieved") or []
            ret_ids = [h.get("chunk_id", "") for h in retrieved]
            ret_docs = [h.get("doc_id", "") for h in retrieved]
            gold_chunks = _split_ids(q.get("gold_chunk_ids", ""))
            gold_docs = _split_ids(q.get("source_docs", ""))

            rec["recall@1"] = round(eval_metrics.recall_at_k(ret_ids, gold_chunks, 1), 4)
            rec["recall@3"] = round(eval_metrics.recall_at_k(ret_ids, gold_chunks, 3), 4)
            rec["recall@5"] = round(eval_metrics.recall_at_k(ret_ids, gold_chunks, 5), 4)
            rec["recall@10"] = round(eval_metrics.recall_at_k(ret_ids, gold_chunks, 10), 4)
            rec["hit@5"] = str(eval_metrics.hit_at_k(ret_ids, gold_chunks, 5)).lower()
            rec["mrr"] = round(eval_metrics.mrr(ret_ids, gold_chunks), 4)
            rec["gold_doc_hit"] = str(eval_metrics.gold_doc_hit(ret_docs, gold_docs, 5)).lower()

            civ = eval_metrics.citation_validity(rec["answer"], res.get("sources") or [])
            rec["citation_total"] = civ["total"]
            rec["citation_valid"] = civ["valid"]
            rec["refused_correct"] = str(
                eval_metrics.refuse_correct(res.get("refused", False),
                                            q["answerable"].strip().lower() == "true")
            ).lower()

            tm = res.get("timing") or {}
            rec["retrieve_ms"] = round(float(tm.get("retrieve", 0.0)) * 1000, 1)
            rec["judge_ms"] = round(float(tm.get("judge", 0.0)) * 1000, 1)
            rec["generate_ms"] = round(float(tm.get("generate", 0.0)) * 1000, 1)
            rec["total_ms"] = round(float(tm.get("total", 0.0)) * 1000, 1)
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"
            print(f"    [错误] {q['qid']} {e}")
            traceback.print_exc()
        records.append(rec)
        print(f"  {q['qid']:<6} [{q['category']:<9}] refused={rec['refused']:<5} "
              f"rc@5={rec['recall@5']:<6} {rec['total_ms']}ms")

    # ---- 追加写（不覆盖历史）----
    write_header = not out_csv.exists() or out_csv.stat().st_size == 0
    with open(out_csv, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        if write_header:
            w.writeheader()
        w.writerows(records)

    summary = _summarize(records, run_id, name, split)
    _print_summary(summary)
    return summary


def _mean(vals):
    """均值。兼容内存中的数值与从 CSV 读回的字符串。"""
    nums = []
    for v in vals:
        if isinstance(v, (int, float)):
            nums.append(float(v))
        else:
            try:
                nums.append(float(v))
            except (TypeError, ValueError):
                continue
    return round(sum(nums) / len(nums), 4) if nums else 0.0


def _summarize(records, run_id, name, split) -> dict:
    ok = [r for r in records if not r["error"]]
    # 检索层只在有 gold 的题上算
    ret_rows = [r for r in ok if r["hit@5"] != "" and
                any(r[k] for k in ("recall@1", "recall@3", "recall@5", "recall@10", "mrr"))
                and r["category"] != "refuse"]

    summary = {
        "run_id": run_id, "system": name, "split": split,
        "n_total": len(records), "n_ok": len(ok), "n_error": len(records) - len(ok),
        "by_category": {}, "overall": {},
        # ★ 拒答主指标：标准二分类口径（拒答=正类）
        "refuse_binary": eval_metrics.refuse_binary_metrics(
            [{"refused": r["refused"], "answerable": r["answerable_gt"]} for r in ok]),
    }
    cats = sorted({r["category"] for r in records})
    for cat in cats:
        rows = [r for r in ok if r["category"] == cat]
        summary["by_category"][cat] = _agg(rows)

    summary["overall"] = _agg(ok)
    summary["by_category"]["_retrieval_only"] = _agg(ret_rows)
    return summary


def _agg(rows) -> dict:
    if not rows:
        return {"n": 0}
    n_ans = sum(1 for r in rows if r["answerable_gt"] == "true")
    refused_cnt = sum(1 for r in rows if r["refused"] == "true")
    over_refusal = sum(1 for r in rows if r["answerable_gt"] == "true" and r["refused"] == "true")
    missed_refusal = sum(1 for r in rows if r["answerable_gt"] == "false" and r["refused"] == "false")
    cite_total = sum(int(r["citation_total"]) for r in rows if r["citation_total"] != "")
    cite_valid = sum(int(r["citation_valid"]) for r in rows if r["citation_valid"] != "")
    return {
        "n": len(rows),
        "recall@1": _mean([r["recall@1"] for r in rows]),
        "recall@3": _mean([r["recall@3"] for r in rows]),
        "recall@5": _mean([r["recall@5"] for r in rows]),
        "recall@10": _mean([r["recall@10"] for r in rows]),
        "mrr": _mean([r["mrr"] for r in rows]),
        "gold_doc_hit": _mean([1 if r["gold_doc_hit"] == "true" else 0 for r in rows]),
        "refused_correct": _mean([1 if r["refused_correct"] == "true" else 0 for r in rows]),
        "over_refusal": over_refusal,
        "missed_refusal": missed_refusal,
        "n_answerable": n_ans, "n_refused": refused_cnt,
        "cite_total": cite_total, "cite_valid": cite_valid,
        "cite_avg": round(cite_total / len(rows), 2),
        "retrieve_ms": _mean([r["retrieve_ms"] for r in rows]),
        "judge_ms": _mean([r["judge_ms"] for r in rows]),
        "generate_ms": _mean([r["generate_ms"] for r in rows]),
        "total_ms": _mean([r["total_ms"] for r in rows]),
    }


def _print_summary(s: dict):
    rb = s.get("refuse_binary", {})
    print("\n" + "=" * 96)
    print(f"汇总  run_id={s['run_id']}  system={s['system']}  split={s['split']}  "
          f"n={s['n_total']} (ok={s['n_ok']}, err={s['n_error']})")
    print("=" * 96)

    # ---- 拒答行为：主指标（标准二分类口径，拒答=正类）----
    print("【拒答行为 · 主指标（二分类口径，拒答=正类）】")
    print(f"  混淆矩阵: tp={rb.get('tp')}(正确拒答)  fp={rb.get('fp')}(过度拒答)  "
          f"fn={rb.get('fn')}(该拒不拒)  tn={rb.get('tn')}(正确放行)")
    print(f"  构成: 应拒答 {rb.get('n_unanswerable')} 题 / 可答 {rb.get('n_answerable')} 题")
    print(f"  ★ 拒答查准率 P = tp/(tp+fp) = {rb.get('precision', 0):.3f}")
    print(f"  ★ 拒答查全率 R = tp/(tp+fn) = {rb.get('recall', 0):.3f}   ← 核心指标（拒答能力）")
    print(f"  ★ F1 = {rb.get('f1', 0):.3f}")
    print(f"  两侧分列: 应拒答侧拒答率 = {rb.get('refuse_rate_on_unanswerable', 0):.3f} | "
          f"可答侧放行率 = {rb.get('pass_rate_on_answerable', 0):.3f}")
    print(f"  [参考值] 总体拒答正确率 = {rb.get('overall_accuracy', 0):.3f}"
          f"  （注：本数据集应拒答题仅占 {rb.get('n_unanswerable')}/{rb.get('n')}，"
          f"该值受类别不平衡影响大，仅供参考）")
    head = (f"{'category':<12}{'n':>4}{'rc@1':>7}{'rc@3':>7}{'rc@5':>7}{'rc@10':>7}"
            f"{'MRR':>7}{'doc@5':>7}{'拒答对':>8}{'过拒':>6}{'该拒不拒':>9}"
            f"{'引用':>7}{'检索ms':>9}{'判定ms':>9}{'生成ms':>9}{'总ms':>9}")
    print(head)
    print("-" * 96)
    for cat, a in s["by_category"].items():
        if a.get("n", 0) == 0:
            continue
        print(f"{cat:<12}{a['n']:>4}{a['recall@1']:>7.3f}{a['recall@3']:>7.3f}"
              f"{a['recall@5']:>7.3f}{a['recall@10']:>7.3f}{a['mrr']:>7.3f}"
              f"{a['gold_doc_hit']:>7.3f}{a['refused_correct']:>8.3f}"
              f"{a['over_refusal']:>6}{a['missed_refusal']:>9}"
              f"{a['cite_avg']:>7.2f}{a['retrieve_ms']:>9.1f}{a['judge_ms']:>9.1f}"
              f"{a['generate_ms']:>9.1f}{a['total_ms']:>9.1f}")
    print("-" * 96)
    a = s["overall"]
    if a.get("n", 0) == 0:
        print(f"{'OVERALL':<12}{0:>4}  （本 run 无成功记录，全部执行失败——请检查 Ollama 服务）")
    else:
        print(f"{'OVERALL':<12}{a['n']:>4}{a['recall@1']:>7.3f}{a['recall@3']:>7.3f}"
              f"{a['recall@5']:>7.3f}{a['recall@10']:>7.3f}{a['mrr']:>7.3f}"
              f"{a['gold_doc_hit']:>7.3f}{a['refused_correct']:>8.3f}"
              f"{a['over_refusal']:>6}{a['missed_refusal']:>9}"
              f"{a['cite_avg']:>7.2f}{a['retrieve_ms']:>9.1f}{a['judge_ms']:>9.1f}"
              f"{a['generate_ms']:>9.1f}{a['total_ms']:>9.1f}")
    print("=" * 96)
