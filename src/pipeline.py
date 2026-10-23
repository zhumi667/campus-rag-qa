"""pipeline.py — 问答链路封装（检索 → 判定 → 生成 → 引用）

把命令行原型（scripts/06_ask.py）的核心逻辑迁移为可复用类 QAPipeline，
供 CLI 与 Web 后端共用。含非流式 ask() 与流式 ask_stream()。

★★★ 安全性硬指标：判定为不可回答（answerable=False）时，
    ask() 直接返回 REFUSE_TEXT、ask_stream() 只发 meta+done，
    【绝不调用生成模型】，timing["generate"] 恒为 0.0。
"""
import csv
import re
import sys
import time
from pathlib import Path

# 项目根入 path（供 `python src/pipeline.py` 直接运行自测；作为库模块被导入时幂等无副作用）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根入 path

import config  # noqa: E402
from src import prompts  # noqa: E402
from src import indexer  # noqa: E402
from src.retriever import get_retriever  # noqa: E402
from src.generator import get_generator, ContextOverflowError  # noqa: E402

# num_ctx=4096；系统提示词与用户模板固定开销约 600-700 token，
# 资料块预算留 2600，总占用控制在 3300 以内，避免溢出。
_CONTEXT_MAX_TOKENS = 2600

# Ollama 的 num_ctx。资料预算 + 系统提示词 + 用户模板 + 问题 必须 <= 该值，
# 否则 Ollama 返回 HTTP 400 "request (N tokens) exceeds the available context size"。
# 注意：固定开销随问题长度浮动，故还有运行时估算兜底（见 _build_answer_context）。
_NUM_CTX = 4096

# 三档预算都放不下时的提示语（仅在极端情况下出现：问题本身极长 + 检索块极长）。
# 与 REFUSE_TEXT 语义不同 —— 后者表示"知识库无依据"，前者表示"这次请求太长"，
# 因此不能复用，否则会把"超长"误报为"没找到"。
_CONTEXT_TOO_LONG_TEXT = ("本次问题的参考内容过长，超出了本地模型的处理上限。"
                          "请精简问题后重试，或改问更具体的点。")

# 引用卡片中原文片段的长度上限（字符）
_SNIPPET_LIMIT = 200

# PDF 按排版宽度硬折行，抽出的文本里每个折行都变成换行（切分器进一步写成空行），
# 于是"因伤\n病休学"这类词被劈开；压成空格后又留下"因伤 病"这种中文词内空格。
# 中文书面语不在字间加空格，故【仅】移除两个汉字之间的空白，其余空白一律保留
# （列表项分隔、标题与正文分隔等结构边界因此不受影响）。
_CJK_SPACE_RE = re.compile(r"([\u4e00-\u9fff])[ \t\r\n]+(?=[\u4e00-\u9fff])")

# 切分器在标题行前保留了 Markdown 标记（全语料约 123 处），
# 卡片里显示 "## 第三十五条" 会显得像排版错误，故仅在展示层去掉标记本身。
_MD_HEADING_RE = re.compile(r"#{1,6}\s*")


def _clean_snippet(raw: str, limit: int = _SNIPPET_LIMIT):
    """把块正文清洗成适合卡片展示的文本。

    返回 (文本, 是否被截断)：
      · 移除被折行劈开的汉字间空白，其余空白压成单个空格
      · 去掉展示用不上的 Markdown 标题标记（## / ### …）
      · 超长时截断并补省略号

    注意：只影响展示，不改动块内容本身；不做列表项合并，以免把并列条目粘连。
    """
    s = _CJK_SPACE_RE.sub(r"\1", raw)
    s = re.sub(r"[ \t\r\n]+", " ", s).strip()
    s = _MD_HEADING_RE.sub("", s).strip()
    if len(s) > limit:
        return s[:limit].rstrip() + "…", True
    return s, False


def _is_generator_refusal(answer: str) -> bool:
    """判断生成模型的输出是否本身就是"拒答话术"。

    ★ 为什么需要它（2026-10-05）：
      判定器（LLM 逐块判定）放行后，生成模型仍可能自行回复
      「知识库中未找到相关依据」。若不在管线层面捕获，会出现：
        · 接口返回 refused=False（看似正常回答）
        · 但 answer 是拒答话术，且 sources 里挂着与问题无关的引用
      用户无法分辨"这是没找到"还是"这是答案"。

    判定方式（不用长度启发式，避免"完整话术"与"话术+补充"落在阈值两侧）：
      ① 以拒答话术开头；且
      ② 去掉话术本身后，剩余部分【只】由引导性词句构成
         （建议 / 请 / 咨询 / 学校 / 相关部门 / 获取 / 准确 / 信息 等）。
      ★ 用"以…开头"而非"包含"：生成 Prompt 明确要求资料不足时只回复这句话，
        因此正常回答不会以它开头；正常回答中引用这句话时它出现在句中，不会命中
        （有单元测试覆盖该情形）。
    """
    from src import prompts

    norm = re.sub(r"[\s。，,.！!？?；;：:、]", "", answer or "")
    if not norm:
        return False
    # 公共前缀取最短话术；完整 REFUSE_TEXT 是它的超集
    t = re.sub(r"[\s。，,.！!？?；;：:、]", "", "知识库中未找到相关依据")
    if not norm.startswith(t):
        return False
    rest = norm[len(t):]
    if not rest:
        return True
    # 允许的引导词：出现在 rest 中即视为"无实质内容的补充说明"
    ALLOWED = ("建议", "请", "咨询", "联系", "学校", "学院", "部门", "相关",
               "获取", "准确", "信息", "进一步", "了解", "或者", "或", "如",
               "教务", "学工", "辅导员", "老师", "工作", "人员", "可")
    residual = rest
    for w in sorted(ALLOWED, key=len, reverse=True):
        residual = residual.replace(w, "")
    # 残留为空或极短 → 确实是拒答话术（无实质内容）
    return len(residual) <= 2


class QAPipeline:
    def __init__(self, strategy="recursive", top_k=None, use_llm_check=True,
                 generator=None, retriever=None):
        self.strategy = strategy
        self.top_k = top_k or config.TOP_K_FINAL
        self.use_llm_check = use_llm_check
        # retriever 可注入（如带重排的实例）；默认沿用单例，行为不变
        self.retriever = retriever or get_retriever(strategy)
        self.generator = generator or get_generator()

    # ------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------
    def _build_sources(self, hits):
        """把检索块转成 sources 列表，idx 从 1 开始，与上下文 [1][2][3] 严格对应。"""
        sources = []
        for i, it in enumerate(hits, start=1):
            body = it.get("text", "")
            hp = it.get("heading_path", "")
            if hp and body.startswith(hp):
                raw = body[len(hp):].lstrip("\n")
            else:
                raw = body
            snippet, truncated = _clean_snippet(raw)
            sources.append({
                "idx": i,
                "chunk_id": it.get("chunk_id", ""),
                "doc_id": it.get("doc_id", ""),
                "doc_title": it.get("doc_title", ""),
                "heading_path": hp,
                "score": float(it.get("score", 0.0)),
                "char_start": int(it.get("char_start", 0)),
                "char_end": int(it.get("char_end", 0)),
                "snippet": snippet,
                "is_truncated": truncated,
                # 来源文档的版本状态（供前端展示"引用自哪个版本"）
                "status": it.get("status", ""),
                "version": it.get("version", ""),
                "family_id": it.get("family_id", ""),
                "effective_date": it.get("effective_date", ""),
                "expire_date": it.get("expire_date", ""),
            })
        return sources

    def _retrieve_and_judge(self, question):
        t0 = time.perf_counter()
        hits = self.retriever.retrieve(question, top_k=self.top_k)
        t_retrieve = time.perf_counter() - t0
        t1 = time.perf_counter()
        judge = self.retriever.is_answerable(question, hits, use_llm_check=self.use_llm_check)
        t_judge = time.perf_counter() - t1
        return hits, judge, t_retrieve, t_judge

    def _answer_with_fallback(self, question, hits):
        """生成回答（非流式）；先估算预算，遇溢出再逐档降级重试。

        流程：_build_answer_context 预选档位 → 若仍溢出则继续降档重试。
        重试耗时如实计入返回的 elapsed；全部失败则向上抛 ContextOverflowError
        （由评测层记入 error，不静默返回空答案——那会被误读为"拒答"）。
        """
        attempts = [
            ("2600", hits, _CONTEXT_MAX_TOKENS),
            ("1300", hits, _CONTEXT_MAX_TOKENS // 2),
            ("top-1 块", hits[:1], _CONTEXT_MAX_TOKENS),
        ]
        # 先用估算挑一个起点，避免必然失败的那一次往返
        ctx, label, est = self._build_answer_context(question, hits)
        start = {"full": 0, "half": 1, "top1": 2}.get(label, 2)

        t0 = time.perf_counter()
        last_err = None
        for i in range(start, len(attempts)):
            lab, use_hits, budget = attempts[i]
            if i > start:
                ctx = prompts.build_context_block(use_hits, max_tokens=budget)
            try:
                res = self.generator.answer(question, ctx)
                return res["text"], time.perf_counter() - t0
            except ContextOverflowError as e:
                last_err = e
                if i + 1 < len(attempts):
                    print(f"    [上下文溢出] {e}，资料预算降至 {attempts[i + 1][0]} 重试")
                else:
                    print(f"    [上下文溢出] {e}，已尝试全部 {len(attempts)} 档预算，仍失败")
        if last_err is None:
            # 估算即判定三档全超（start=2 已跑过），仍失败时给出明确的溢出异常
            last_err = ContextOverflowError(
                f"request ({est} tokens) exceeds the available context size ({_NUM_CTX} tokens)")
        raise last_err

    # ------------------------------------------------------------
    # 上下文预算：溢出安全构建
    # ------------------------------------------------------------
    @staticmethod
    def _estimate_total_tokens(context: str, question: str) -> int:
        """估算一次生成请求的总 token 数（资料 + 系统提示词 + 用户模板 + 问题）。

        对应 Ollama 的 "request (N tokens) exceeds the available context size"。
        用 utils.estimate_tokens 逐段累加，比按整串估算更稳（模板与资料的语言构成不同）。
        """
        from src import utils

        return (utils.estimate_tokens(context)
                + utils.estimate_tokens(prompts.QA_SYSTEM_PROMPT)
                + utils.estimate_tokens(prompts.QA_USER_TEMPLATE)
                + utils.estimate_tokens(question))

    def _build_answer_context(self, question, hits, tag=""):
        """构建【保证不超 num_ctx】的资料块。

        为什么需要它：流式路径一旦开始吐字就无法回退重试，因此必须在【调用生成之前】
        就选好不会溢出的档位；非流式路径虽有逐档重试，但先算一遍可省掉一次失败往返。

        档位：full(2600) → half(1300) → top-1 块。三档都溢出时返回最后一档，
        由调用方决定如何处理（非流式向上抛、流式回友好提示）。
        """
        attempts = [
            ("full", hits, _CONTEXT_MAX_TOKENS),
            ("half", hits, _CONTEXT_MAX_TOKENS // 2),
            ("top1", hits[:1], _CONTEXT_MAX_TOKENS),
        ]
        ctx, final_budget = "", _CONTEXT_MAX_TOKENS
        for i, (label, use_hits, budget) in enumerate(attempts):
            ctx = prompts.build_context_block(use_hits, max_tokens=budget)
            final_budget = budget
            est = self._estimate_total_tokens(ctx, question)
            if est <= _NUM_CTX:
                if i > 0:
                    print(f"    [上下文预算] 估算 {est} > {_NUM_CTX}，"
                          f"已降至 {label}（预算 {budget}）")
                return ctx, label, est
        print(f"    [上下文预算] 三档均超限，估算 {self._estimate_total_tokens(ctx, question)} "
              f"> {_NUM_CTX}（已用最小档 top1 / 预算 {final_budget}）")
        return ctx, "overflow", self._estimate_total_tokens(ctx, question)

    # ------------------------------------------------------------
    # 非流式
    # ------------------------------------------------------------
    def ask(self, question: str, history: list = None) -> dict:
        hits, judge, t_retrieve, t_judge = self._retrieve_and_judge(question)
        refused = not judge["answerable"]
        # retrieved 与 sources 用同一结构；拒答时 sources 为空，retrieved 始终保留完整结构
        built = self._build_sources(hits)
        sources = [] if refused else built

        if refused:
            # 不可回答：强制返回 REFUSE_TEXT，绝不调用生成模型
            answer = prompts.REFUSE_TEXT
            t_generate = 0.0
            stage = judge.get("stage", "")
        else:
            answer, t_generate = self._answer_with_fallback(question, hits)
            # ★ 生成器侧拒答守卫（2026-10-05 新增）
            #   判定器放行后，生成模型仍可能自行输出拒答话术（实测存在，占判定
            #   通过题的一部分）。若不捕获，前端会显示 refused=False 却给出
            #   「知识库中未找到相关依据」，用户无法分辨，且会附带无依据的引用。
            #   这里统一按拒答处理，并在 judge.stage 上标注 post_refuse 便于统计。
            if _is_generator_refusal(answer):
                refused = True
                sources = []
                stage = "post_refuse"
            else:
                stage = ""

        total = t_retrieve + t_judge + t_generate
        return {
            "question": question,
            "answer": answer,
            "error": "",
            "refused": refused,
            "refuse_stage": stage,
            "sources": sources,
            "retrieved": built,
            "timing": {
                "retrieve": round(t_retrieve, 3),
                "judge": round(t_judge, 3),
                "generate": round(t_generate, 3),
                "total": round(total, 3),
            },
            "judge": judge,
        }

    # ------------------------------------------------------------
    # 流式
    # ------------------------------------------------------------
    def ask_stream(self, question: str, history: list = None):
        try:
            hits, judge, t_retrieve, t_judge = self._retrieve_and_judge(question)
        except Exception as e:
            yield {"type": "error", "message": str(e)}
            return

        refused = not judge["answerable"]
        # retrieved 与 sources 用同一结构；拒答时 sources 为空，retrieved 始终保留完整结构
        built = self._build_sources(hits)
        sources = [] if refused else built

        # 1) 先发 meta（含 sources/retrieved/refused/judge/timing），前端据此先渲染引用卡片
        yield {"type": "meta", "sources": sources, "retrieved": built, "refused": refused,
               "judge": judge,
               "timing": {"retrieve": round(t_retrieve, 3), "judge": round(t_judge, 3),
                          "generate": 0.0}}

        if refused:
            # 拒答：meta 之后直接 done，绝不调用生成模型
            yield {"type": "done",
                   "timing": {"generate": 0.0, "total": round(t_retrieve + t_judge, 3)}}
            return

        # ★ 流式路径的关键约束：一旦开始 yield token 就无法回退重试，
        #   因此必须在【调用生成之前】按 token 预算选好不会溢出的档位。
        ctx, budget_label, est = self._build_answer_context(question, hits)

        if budget_label == "overflow":
            # 三档都超限：不再强行调用生成（否则会在吐字中途抛 HTTP 400），
            # 而是回一条明确的提示，前端按普通回答渲染即可。
            print(f"    [上下文溢出] 估算 {est} > {_NUM_CTX}，三档均超限，返回友好提示")
            yield {"type": "token", "text": _CONTEXT_TOO_LONG_TEXT}
            yield {"type": "done",
                   "timing": {"generate": 0.0, "total": round(t_retrieve + t_judge, 3)}}
            return

        t2 = time.perf_counter()
        gen_parts = []
        try:
            for piece in self.generator.answer_stream(question, ctx):
                gen_parts.append(piece)
                yield {"type": "token", "text": piece}
        except ContextOverflowError as e:
            # 兜底：估算未预警但实际仍溢出（问题特别长或模板变动）。此时可能已吐过字，
            # 不能重试，只能明确告知用户，而不是抛 500 或静默截断。
            print(f"    [上下文溢出] 流式过程中实际溢出：{e}")
            yield {"type": "token", "text": _CONTEXT_TOO_LONG_TEXT}
            yield {"type": "done",
                   "timing": {"generate": round(time.perf_counter() - t2, 3),
                              "total": round(t_retrieve + t_judge + time.perf_counter() - t2, 3)}}
            return
        except Exception as e:
            yield {"type": "error", "message": str(e)}
            return
        t_generate = time.perf_counter() - t2
        # ★ 生成器侧拒答守卫（与 ask() 一致）。
        #   流式路径无法撤回已发出的 token，因此这里只在 done 帧上把 refused 纠正为
        #   True，让前端据此改渲染为拒答提示（前端已按 refused 决定展示样式）。
        if _is_generator_refusal("".join(gen_parts)):
            print("    [生成器拒答守卫] 判定器放行但生成模型输出拒答话术，按拒答处理")
            yield {"type": "refused_override", "refused": True,
                   "answer": prompts.REFUSE_TEXT, "refuse_stage": "post_refuse"}
            yield {"type": "done",
                   "timing": {"generate": round(t_generate, 3),
                              "total": round(t_retrieve + t_judge + t_generate, 3)}}
            return
        yield {"type": "done",
               "timing": {"generate": round(t_generate, 3),
                          "total": round(t_retrieve + t_judge + t_generate, 3)}}

    # ------------------------------------------------------------
    # 健康检查
    # ------------------------------------------------------------
    def health(self) -> dict:
        ollama = self.generator.health()
        idx = indexer.get_index(self.strategy)
        index_info = {"size": idx.size, "dim": idx.dim}

        docs = 0
        with open(config.META_CSV, "r", encoding="utf-8-sig", newline="") as f:
            docs = sum(1 for _ in csv.DictReader(f))

        chunks = 0
        chunks_jsonl = config.CHUNK_DIR / f"chunks_{self.strategy}.jsonl"
        if chunks_jsonl.exists():
            with open(chunks_jsonl, "r", encoding="utf-8") as f:
                chunks = sum(1 for line in f if line.strip())

        ok = bool(ollama.get("ok")) and index_info["size"] > 0
        return {"ok": ok, "ollama": ollama, "index": index_info,
                "corpus": {"docs": docs, "chunks": chunks}}


if __name__ == "__main__":
    print("=" * 72)
    print("pipeline 自测")
    print("=" * 72)

    p = QAPipeline()

    print("\n[1] health()")
    print(p.health())

    questions = [
        "考试不及格可以补考吗",
        "国家奖学金的申请条件是什么",
        "今天食堂有什么菜",
    ]
    for q in questions:
        print("\n" + "=" * 72)
        print(f"ask(): {q}")
        print("=" * 72)
        r = p.ask(q)
        print(f"answer: {r['answer']}")
        print(f"refused: {r['refused']}  refuse_stage: {r['refuse_stage']}")
        print(f"timing: {r['timing']}")
        for s in r["sources"][:3]:
            print(f"  source[{s['idx']}] {s['doc_title']} | {s['heading_path']} | score={s['score']:.4f}")

    print("\n" + "=" * 72)
    print("ask_stream(): 今天食堂有什么菜（拒答，应为 meta → done，无 token）")
    print("=" * 72)
    for ev in p.ask_stream("今天食堂有什么菜"):
        print(f"  event={ev['type']}  data={ {k: v for k, v in ev.items() if k != 'type'} }")
