"""eval_metrics.py — 评测指标（纯函数，不依赖外部服务，便于单测）

检索层指标（自动）：recall_at_k / hit_at_k / mrr / gold_doc_hit
行为层指标（自动）：citation_validity / refuse_correct

★ 说明：citation_validity 只校验"引用编号是否有效"（回答里的 [n] 能否在
  sources 的 idx 中找到），【不做】语义支持性判断（后者需人工或更强模型）。
"""
import re

# 匹配回答中的引用标记，如 [1] [2]
_CITE_RE = re.compile(r"\[(\d+)\]")


def recall_at_k(retrieved_chunk_ids, gold_chunk_ids, k: int) -> float:
    """top-k 中命中的 gold 块数 / gold 块总数。

    gold 为空（如拒答题）时返回 0.0，不报错。
    """
    if not gold_chunk_ids:
        return 0.0
    gold = set(gold_chunk_ids)
    topk = set(list(retrieved_chunk_ids)[:k])
    return len(gold & topk) / len(gold)


def hit_at_k(retrieved_chunk_ids, gold_chunk_ids, k: int) -> bool:
    """top-k 中是否至少命中一个 gold 块（二值）。gold 为空返回 False。"""
    if not gold_chunk_ids:
        return False
    gold = set(gold_chunk_ids)
    return any(cid in gold for cid in list(retrieved_chunk_ids)[:k])


def mrr(retrieved_chunk_ids, gold_chunk_ids) -> float:
    """第一个命中 gold 的位置的倒数（1/rank）。

    ★ 全量检索列表参与计算（不是只看 top-k）；未命中返回 0.0。
    """
    if not gold_chunk_ids:
        return 0.0
    gold = set(gold_chunk_ids)
    for i, cid in enumerate(retrieved_chunk_ids, start=1):
        if cid in gold:
            return 1.0 / i
    return 0.0


def gold_doc_hit(retrieved_doc_ids, gold_doc_ids, k: int) -> bool:
    """top-k 中是否命中 gold 文档（块级 gold 缺失时的兜底指标）。"""
    if not gold_doc_ids:
        return False
    gold = set(gold_doc_ids)
    return any(d in gold for d in list(retrieved_doc_ids)[:k])


def citation_validity(answer: str, sources: list) -> dict:
    """校验回答中每个 [n] 引用标记能否在 sources 中找到对应 idx。

    返回 {"total": 引用总数, "valid": 有效数, "invalid_idx": [无效编号...]}
    ★ 只校验编号有效性，不做语义支持性判断。
    """
    valid_idx = {s.get("idx") for s in (sources or [])}
    found = [int(m) for m in _CITE_RE.findall(answer or "")]
    invalid = sorted({n for n in found if n not in valid_idx})
    valid_count = sum(1 for n in found if n in valid_idx)
    return {"total": len(found), "valid": valid_count, "invalid_idx": invalid}


def refuse_correct(refused: bool, answerable: bool) -> bool:
    """行为正确性：拒答题应拒答、可答题不应拒答。"""
    return bool(refused) == (not bool(answerable))


def _as_bool(v) -> bool:
    """兼容 bool 与从 CSV 读回的 'true'/'false' 字符串。"""
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes")


def refuse_binary_metrics(records: list) -> dict:
    """拒答的二分类指标（把「拒答」视为正类）。

    records：每题含 {"refused": bool, "answerable": bool}
      · refused    = 系统拒答（预测为正）
      · answerable = 标注是否可回答（answerable=False 即"应拒答"）

    ★ 为什么不能只看 overall_accuracy：本数据集应拒答题仅 4/61，
      一个"从不拒答"的系统也能拿到 57/61 = 0.934，该值受类别不平衡影响严重。
      正确做法是同时报告 precision / recall / F1 与两侧分列。
    """
    tp = fp = fn = tn = 0
    for r in records:
        refused = _as_bool(r.get("refused"))
        answerable = _as_bool(r.get("answerable"))
        if not answerable and refused:
            tp += 1          # 应拒答且拒答 → 正确拒答
        elif answerable and refused:
            fp += 1          # 可答却拒答   → 过度拒答
        elif not answerable and not refused:
            fn += 1          # 应拒答却未拒答 → 该拒不拒
        else:
            tn += 1          # 可答且未拒答  → 正确放行
    n = tp + fp + fn + tn
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "n": n,
        "n_answerable": tn + fp,
        "n_unanswerable": tp + fn,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "refuse_rate_on_unanswerable": round(recall, 4),
        "pass_rate_on_answerable": round(tn / (tn + fp), 4) if (tn + fp) else 0.0,
        "overall_accuracy": round((tp + tn) / n, 4) if n else 0.0,
    }


# ============================================================
# 单测（python src/eval_metrics.py）
# ============================================================
if __name__ == "__main__":
    passed = 0
    failed = 0

    def check(name, got, want):
        global passed, failed
        ok = got == want
        flag = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        print(f"  [{flag}] {name}: got={got!r} want={want!r}")

    print("=" * 72)
    print("eval_metrics 单测")
    print("=" * 72)

    gold = ["c1", "c2"]
    print("\n[1] recall_at_k")
    check("完全命中@5", recall_at_k(["c1", "c2", "c3"], gold, 5), 1.0)
    check("部分命中@5", recall_at_k(["c1", "x", "y"], gold, 5), 0.5)
    check("完全不命中@5", recall_at_k(["x", "y", "z"], gold, 5), 0.0)
    check("空 gold 返回 0", recall_at_k(["c1"], [], 5), 0.0)
    check("空检索 返回 0", recall_at_k([], gold, 5), 0.0)
    check("k 截断（命中在 k 之外不计）", recall_at_k(["x", "c1"], gold, 1), 0.0)

    print("\n[2] hit_at_k")
    check("命中@3", hit_at_k(["x", "y", "c1"], gold, 3), True)
    check("未命中@3（命中在 k 外）", hit_at_k(["x", "y", "c1"], gold, 2), False)
    check("空 gold", hit_at_k(["c1"], [], 5), False)

    print("\n[3] mrr（全量参与）")
    check("第1位命中", mrr(["c1", "x"], gold), 1.0)
    check("第3位命中", mrr(["x", "y", "c2"], gold), 1 / 3)
    check("未命中返回 0", mrr(["x", "y"], gold), 0.0)
    check("空 gold 返回 0", mrr(["c1"], []), 0.0)
    check("命中在 top-k 之外也算（全量）", mrr(["x", "y", "z", "c1"], gold), 1 / 4)

    print("\n[4] gold_doc_hit")
    check("文档命中@2", gold_doc_hit(["d1", "d9"], ["d1"], 2), True)
    check("文档未命中", gold_doc_hit(["d9"], ["d1"], 5), False)
    check("空 gold_docs", gold_doc_hit(["d1"], [], 5), False)

    print("\n[5] citation_validity")
    srcs = [{"idx": 1}, {"idx": 2}, {"idx": 3}]
    check("全部有效", citation_validity("结论A[1]，结论B[2]", srcs),
          {"total": 2, "valid": 2, "invalid_idx": []})
    check("含无效编号 [9]", citation_validity("结论A[1]，结论B[9]", srcs),
          {"total": 2, "valid": 1, "invalid_idx": [9]})
    check("无引用", citation_validity("没有编号", srcs),
          {"total": 0, "valid": 0, "invalid_idx": []})
    check("sources 为空时任何编号都无效", citation_validity("结论[1]", []),
          {"total": 1, "valid": 0, "invalid_idx": [1]})
    check("空回答", citation_validity("", srcs), {"total": 0, "valid": 0, "invalid_idx": []})

    print("\n[6] refuse_correct")
    check("拒答题拒答 → 正确", refuse_correct(True, False), True)
    check("拒答题未拒答 → 错误", refuse_correct(False, False), False)
    check("可答题未拒答 → 正确", refuse_correct(False, True), True)
    check("可答题被拒答 → 错误", refuse_correct(True, True), False)

    print("\n[7] refuse_binary_metrics")
    # 场景1：从不拒答的系统（57 可答 + 4 应拒答），accuracy 高但 recall=0
    recs_never = [{"refused": False, "answerable": True}] * 57 + \
                 [{"refused": False, "answerable": False}] * 4
    m = refuse_binary_metrics(recs_never)
    check("从不拒答: tp/fp/fn/tn", (m["tp"], m["fp"], m["fn"], m["tn"]), (0, 0, 4, 57))
    check("从不拒答: recall(拒答能力)=0", m["recall"], 0.0)
    check("从不拒答: precision=0", m["precision"], 0.0)
    check("从不拒答: overall_accuracy 仍很高(误导)", m["overall_accuracy"], 0.9344)
    check("从不拒答: 可答侧放行率=1", m["pass_rate_on_answerable"], 1.0)

    # 场景2：有拒答能力但过度拒答
    recs_b3 = [{"refused": True, "answerable": False}] * 4 + \
              [{"refused": True, "answerable": True}] * 15 + \
              [{"refused": False, "answerable": True}] * 42
    m2 = refuse_binary_metrics(recs_b3)
    check("b3式: 混淆矩阵", (m2["tp"], m2["fp"], m2["fn"], m2["tn"]), (4, 15, 0, 42))
    check("b3式: precision=4/19", m2["precision"], 0.2105)
    check("b3式: recall=1.0（拒答能力满分）", m2["recall"], 1.0)
    check("b3式: 可答侧放行率=42/57", m2["pass_rate_on_answerable"], 0.7368)
    check("b3式: f1>0", m2["f1"] > 0, True)

    # 场景3：字符串输入（从 CSV 读回）
    recs_str = [{"refused": "true", "answerable": "false"},
                {"refused": "false", "answerable": "true"}]
    check("CSV 字符串兼容", refuse_binary_metrics(recs_str)["n"], 2)

    # 场景4：空输入
    check("空输入不报错", refuse_binary_metrics([])["n"], 0)

    print("\n" + "=" * 72)
    print(f"单测结果: {passed} passed, {failed} failed")
    print("=" * 72)
