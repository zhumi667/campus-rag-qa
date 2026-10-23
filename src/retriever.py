"""retriever.py — 检索统一入口（本轮只做纯稠密检索，不做 BM25 / 混合 / 重排）

说明：实测检索答案 93% 位于 top-3（平均 rank 1.2），故拒答判定主要依赖
逐块 LLM 判定 + 相似度阈值；Cross-Encoder 重排留待阶段三作为对照实验
（预期收益有限，需实验验证）。
"""
import csv
import datetime
import re
import time

import config  # noqa: E402
from src import utils  # noqa: E402
from src import indexer  # noqa: E402


class Retriever:
    def __init__(self, strategy: str = "recursive", index=None, use_rerank: bool = False):
        self.strategy = strategy
        self.index = index or indexer.get_index(strategy)
        self.use_rerank = use_rerank          # ★ 可选开关，默认 False（不改变既有行为）
        self._chunks = self._load_chunks()
        self._meta = self._load_meta()
        self._reranker = None
        self.last_rerank_elapsed = 0.0        # 最近一次重排耗时（秒），与检索耗时分离
        self.last_reranked_all = []           # 最近一次重排后的完整列表（供评估取 top-10）

    def _load_chunks(self) -> dict:
        """启动时读一次 JSONL 并缓存（块信息不要每次检索都重读）。"""
        jsonl = config.CHUNK_DIR / f"chunks_{self.strategy}.jsonl"
        return {c["chunk_id"]: c for c in utils.read_jsonl(jsonl)}

    def _load_meta(self) -> dict:
        meta = {}
        with open(config.META_CSV, "r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                meta[row["doc_id"]] = row
        return meta

    def retrieve(self, query: str, top_k: int = None, score_threshold: float = None) -> list:
        """稠密检索，返回按 score 降序的块列表（含 doc_title 与文档状态）。

        use_rerank=True 时：召回 top-RERANK_TOP_K → Cross-Encoder 重排 → 取 top_k。
        重排耗时记录在 self.last_rerank_elapsed（与检索耗时分离，便于统计）。

        ★ 状态过滤（VERSION_FILTER_ENABLED）开启时会剔除不可检索文档的块，
          为避免"滤完不足 top_k"，此时按 RETRIEVE_OVERFETCH 倍超取候选。
        """
        top_k = top_k or config.TOP_K_FINAL
        if self.use_rerank:
            return self._retrieve_with_rerank(query, top_k, score_threshold)

        fetch_k = self._fetch_k(top_k)
        hits = self.index.search(query, top_k=fetch_k)
        results = []
        for h in hits:
            item = self._to_item(h)
            if item is None:                      # 被状态/有效期过滤掉
                continue
            if score_threshold is not None and item["score"] < score_threshold:
                continue
            results.append(item)
            if len(results) >= top_k:
                break
        # ★ 过滤会剔除部分候选，rank 必须重排为最终位次（0 基），
        #   否则下游按 rank 展示的 "#序号" 会跳号。
        for i, it in enumerate(results):
            it["rank"] = i
        return results

    def _fetch_k(self, top_k: int) -> int:
        """按 top_k 计算实际召回数：状态过滤开启时超取，否则原样返回。

        ★ 为什么要超取：过滤发生在检索之后，若只取 top_k，被滤掉若干条后
          返回数会少于 top_k，导致送入生成的资料变少、且 rank 语义变化。
          超取比例由 config.RETRIEVE_OVERFETCH 控制（默认 3），上限 200。
        """
        if not getattr(config, "VERSION_FILTER_ENABLED", False):
            return top_k
        mult = max(1, int(getattr(config, "RETRIEVE_OVERFETCH", 3)))
        return min(top_k * mult, 200)

    def _to_item(self, h: dict):
        """把索引命中转成带块信息的检索结果项（重排前后共用）。

        ★ 返回 None 表示该块所属文档当前不可检索（status 非 active，
          或生效日期晚于当前基准日期，或已被 expire_date 标记失效）。
          调用方必须判 None —— 这样过滤逻辑对"直接检索"与"重排路径"同时生效，
          不会出现只过滤了一条路径的漏洞。
        """
        cid = h["chunk_id"]
        c = self._chunks.get(cid, {})
        doc_id = c.get("doc_id", "")
        m = self._meta.get(doc_id, {})
        if not self._is_retrievable(m):
            return None
        return {
            "chunk_id": cid,
            "score": h["score"],
            "rank": h["rank"],
            "text": c.get("text", ""),
            "heading_path": c.get("heading_path", ""),
            "doc_id": doc_id,
            "char_start": c.get("char_start", 0),
            "char_end": c.get("char_end", 0),
            "doc_title": m.get("title", doc_id),
            # ★ 以下字段供前端展示"该文档的版本/生效状态"，并用于展示失效提示
            "status": m.get("status", ""),
            "version": m.get("version", ""),
            "family_id": m.get("family_id", ""),
            "effective_date": m.get("effective_date", ""),
            "expire_date": m.get("expire_date", ""),
        }

    def _is_retrievable(self, meta: dict) -> bool:
        """判断某文档当前是否可被检索（版本冲突处理的接入点）。

        规则（VERSION_FILTER_ENABLED 为 False 时一律放行，保持既有行为）：
          ① status 必须是 active（inactive=已失效 / draft=草稿，都不应被引用）
          ② effective_date 若存在，必须 <= 基准日期（未生效的不能引用）
          ③ expire_date 若存在，必须 > 基准日期（已过期的不能引用）
          基准日期 = config.DEFAULT_AS_OF_DATE，为空时取今天。

        ★ 为什么用"日期区间"而不是"同族只留最新"：
          同族多版本在检索期做"只留最新"需要先知道命中了哪些族，会引入
          全局状态；而 status + 生效/失效日期是【文档自身的属性】，
          逐块判断即可，且能表达"某版本在 2023-2025 有效"这类区间语义。
          多版本共存时，靠 03_register 的校验（同族仅一个 active）保证唯一性。
        """
        if not getattr(config, "VERSION_FILTER_ENABLED", False):
            return True

        status = (meta.get("status") or "active").strip().lower()
        if status != "active":
            return False

        as_of = getattr(config, "DEFAULT_AS_OF_DATE", None) or datetime.date.today().isoformat()
        eff = (meta.get("effective_date") or "").strip()
        exp = (meta.get("expire_date") or "").strip()
        if eff and eff > as_of:      # 尚未生效
            return False
        if exp and exp <= as_of:     # 已失效
            return False
        return True

    def _retrieve_with_rerank(self, query: str, top_k: int, score_threshold: float) -> list:
        """召回 top-RERANK_TOP_K → 重排 → 取 top_k（rank 字段改为重排后名次）。

        ★ 与直接检索一致地应用状态过滤（_to_item 返回 None 即剔除），
          并在过滤开启时对召回数超取，避免滤完候选过少。
        """
        recall_k = self._fetch_k(getattr(config, "RERANK_TOP_K", 20))
        hits = self.index.search(query, top_k=recall_k)
        results = []
        for h in hits:
            item = self._to_item(h)
            if item is None:
                continue
            if score_threshold is not None and item["score"] < score_threshold:
                continue
            results.append(item)

        if self._reranker is None:
            from src.reranker import get_reranker
            self._reranker = get_reranker()
        reranked = self._reranker.rerank(query, results)   # 全量（不截断），便于取 top-10
        self.last_rerank_elapsed = self._reranker.last_elapsed
        self.last_reranked_all = reranked

        top = reranked[:top_k]
        for i, it in enumerate(top):
            it["rank"] = i     # 下游按 rank 展示，改为重排后名次
        return top

    def is_answerable(self, question: str, results: list,
                      threshold: float = None, use_llm_check: bool = True,
                      use_rerank: bool = None, max_check: int = None) -> dict:
        """判定检索结果是否足以回答（question 为必填位置参数）。

        返回 {"answerable": bool, "reason": str, "stage": str, "elapsed": float,
              "chunks_checked": int, "yes_chunk_id": str}
        stage: empty（无结果）/ threshold（阈值初筛拒答）/ llm（LLM 二次判定）/ pass（跳过 LLM）

        ★ use_rerank：None 时取 self.use_rerank。
          启用重排时【必须】跳过基于绝对分数的两道门限（阈值初筛 0.45 与早停 0.62）：
          这两个阈值都是按【稠密相似度】标定的，而重排后排序由 rerank_score 决定，
          results[0]["score"] 仍是该块的稠密分数 —— 重排把更相关的块提上来时，
          其稠密分数往往更低，"排第 1 却过不了门限"，会出现
          「重排越正确、越容易被拒答」的反常现象。故重排路径一律交给 LLM 逐块判定。

        ★ max_check：判定器逐块检查的最大块数；None 时取 config.JUDGE_MAX_CHECK（默认 3），
          显式传参时以传参为准（阶段三 max_check 消融实验用）。
        """
        if use_rerank is None:
            use_rerank = getattr(self, "use_rerank", False)
        if threshold is None:
            threshold = getattr(config, "SCORE_THRESHOLD", None)
            if threshold is None:
                threshold = 0.45   # 兜底，正常情况下 config 已提供
        if not results:
            return {"answerable": False, "reason": "无检索结果",
                    "stage": "empty", "elapsed": 0.0,
                    "chunks_checked": 0, "yes_chunk_id": ""}
        if use_rerank:
            # 重排路径：跳过绝对分数门限，直接进 LLM 判定
            if use_llm_check:
                v = verify_answerable(question, results, allow_early_stop=False,
                                      max_check=max_check)
                return {"answerable": v["answerable"], "reason": v["reason"],
                        "stage": "llm", "elapsed": v.get("elapsed", 0.0),
                        "chunks_checked": v.get("chunks_checked", 0),
                        "yes_chunk_id": v.get("yes_chunk_id", "")}
            return {"answerable": True, "reason": "跳过 LLM 判定（调试用）",
                    "stage": "pass", "elapsed": 0.0,
                    "chunks_checked": 0, "yes_chunk_id": results[0].get("chunk_id", "")}
        if results[0]["score"] < threshold:
            return {"answerable": False,
                    "reason": f"top1 分数 {results[0]['score']:.4f} < 阈值 {threshold}",
                    "stage": "threshold", "elapsed": 0.0,
                    "chunks_checked": 0, "yes_chunk_id": results[0].get("chunk_id", "")}
        if use_llm_check:
            v = verify_answerable(question, results, max_check=max_check)
            return {"answerable": v["answerable"], "reason": v["reason"],
                    "stage": "llm", "elapsed": v.get("elapsed", 0.0),
                    "chunks_checked": v.get("chunks_checked", 0),
                    "yes_chunk_id": v.get("yes_chunk_id", "")}
        return {"answerable": True, "reason": "跳过 LLM 判定（调试用）",
                "stage": "pass", "elapsed": 0.0,
                "chunks_checked": 0, "yes_chunk_id": results[0].get("chunk_id", "")}


_RETRIEVERS = {}


def get_retriever(strategy: str = "recursive") -> Retriever:
    if strategy not in _RETRIEVERS:
        _RETRIEVERS[strategy] = Retriever(strategy=strategy)
    return _RETRIEVERS[strategy]


def _parse_verdict(text: str):
    """解析 LLM 判定输出，返回 (answerable, confidence)。

    优先匹配「结论：YES/NO」；匹配不到再回退全文搜索 YES/NO（取最后出现的，
    因为结论通常在末尾）；仍解析不出则保守返回 (False, 0.0)。
    """
    m = re.search(r"结论\s*[:：]\s*(YES|NO)", text, re.IGNORECASE)
    if m:
        return (m.group(1).upper() == "YES"), 1.0
    upper = text.upper()
    yes_pos = upper.rfind("YES")
    no_pos = upper.rfind("NO")
    if yes_pos > no_pos:
        return True, 0.8
    if no_pos > yes_pos:
        return False, 0.8
    return False, 0.0  # 解析不出来，保守拒答


def verify_answerable(question: str, hits: list,
                      generator=None, max_check: int = None,
                      early_stop_score: float = 0.62,
                      allow_early_stop: bool = True) -> dict:
    """逐块判定：对 top-max_check 的每块单独问 LLM，任一 YES 即放行。

    max_check：判定器检查的最大块数；None 时取 config.JUDGE_MAX_CHECK（默认 3），
               显式传参时以传参为准（阶段三 max_check 消融实验用）。

    early_stop_score：若 rank1 分数 >= 该值，直接判可回答，跳过 LLM（省时间）

    ★ allow_early_stop 的使用纪律：
      早停的前提是「rank1 的 score 与 early_stop_score 来自同一条排序链、量纲可比」。
      该阈值 0.62 是按【稠密相似度】标定的，因此仅在 use_rerank=False 时成立。
      启用重排后 hits[i]["score"] 仍是稠密相似度，而排序已由 rerank_score 决定 ——
      此时"排在第 1"的块其稠密分数可能天然偏低（重排的作用恰恰是纠正稠密的错误排序），
      若仍用 0.62 判定，会出现「重排越正确、越容易掉进 LLM 判定」的反常现象
      （实测：dev 集重排后有 30/61 题的 rank1 稠密分数低于 0.62）。
      故调用方必须在启用重排时传 allow_early_stop=False。

    返回 {"answerable","reason","confidence","elapsed",
          "chunks_checked","yes_chunk_id","raw_head"}
    """
    from src import prompts
    if generator is None:
        from src.generator import get_generator
        generator = get_generator()
    if max_check is None:
        max_check = getattr(config, "JUDGE_MAX_CHECK", 3)   # 默认 3，可显式覆盖

    # 1. 空结果
    if not hits:
        return {"answerable": False, "reason": "无检索结果",
                "confidence": 0.0, "elapsed": 0.0,
                "chunks_checked": 0, "yes_chunk_id": "", "raw_head": ""}

    # 2. 早停优化：rank1 分数足够高，直接放行（不调 LLM）
    #    ★ 仅当分数与阈值量纲可比时才允许（见 docstring）
    top1 = hits[0]
    if allow_early_stop and top1["score"] >= early_stop_score:
        print(f"    [逐块判定] 早停: rank1 {top1['chunk_id']} 分数 {top1['score']:.4f} >= {early_stop_score}，直接放行")
        return {"answerable": True, "reason": "早停（rank1 高分）",
                "confidence": 1.0, "elapsed": 0.0,
                "chunks_checked": 0, "yes_chunk_id": top1["chunk_id"], "raw_head": ""}
    if not allow_early_stop:
        print(f"    [逐块判定] 早停已禁用（重排后的 score 与阈值不可比），进入逐块判定")

    # 3. 逐块判定
    t0 = time.perf_counter()
    first_text = ""
    checked = 0
    for h in hits[:max_check]:
        body = h.get("text", "")
        hp = h.get("heading_path", "")
        if hp and body.startswith(hp):
            body = body[len(hp):].lstrip("\n")
        chunk_text = body[:1200]
        user = prompts.VERIFY_SINGLE_PROMPT.format(question=question, chunk=chunk_text)
        t1 = time.perf_counter()
        res = generator.chat("你是严格的资料相关性判定助手。", user, max_tokens=30)
        dt = time.perf_counter() - t1
        checked += 1
        text = res["text"].strip()
        if first_text == "":
            first_text = text
        answerable, confidence = _parse_verdict(text)
        verdict = "YES" if answerable else "NO"
        suffix = " → 放行" if answerable else ""
        print(f"    [逐块判定] 块{checked}/{max_check} {h['chunk_id']} 结论：{verdict} ({dt:.1f}s){suffix}")
        if answerable:
            elapsed = time.perf_counter() - t0
            return {"answerable": True, "reason": first_text,
                    "confidence": confidence, "elapsed": elapsed,
                    "chunks_checked": checked, "yes_chunk_id": h["chunk_id"],
                    "raw_head": first_text[:80]}

    elapsed = time.perf_counter() - t0
    return {"answerable": False, "reason": first_text,
            "confidence": 0.0, "elapsed": elapsed,
            "chunks_checked": checked, "yes_chunk_id": "",
            "raw_head": first_text[:80]}


if __name__ == "__main__":
    r = get_retriever()
    questions = [
        "考试不及格可以补考吗",
        "转专业需要什么条件",
        "学生可以申请休学吗",
        "对成绩有异议怎么处理",
        "连续旷课多少学时会被处理",
        "今天天气怎么样",
    ]
    for q in questions:
        hits = r.retrieve(q, top_k=3)
        ans = r.is_answerable(q, hits)
        print(f"\n问题: {q}")
        print(f"  is_answerable: {ans['answerable']} (stage={ans['stage']})")
        for it in hits:
            print(f"  #{it['rank'] + 1} {it['chunk_id']:20} {it['score']:.4f}  "
                  f"{it['doc_title'][:20]} | {it['heading_path'][:40]}")
