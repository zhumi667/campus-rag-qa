"""baselines.py — E4「整体基线对比」的三个基线

B1 BareLLM   ：裸模型，不给任何资料（证明"不做检索增强会怎样"）
B2 NaiveRAG  ：朴素 RAG，★独立实现（固定长度切分 + 自己的 FAISS 索引 + 自己的 prompt）
B3 FullSystem：完整系统，包装 src/pipeline.py 的 QAPipeline（保持现有行为不变）

★ B2 纪律：不复用 src/retriever.py 与 src/pipeline.py。
  仅复用 src/embedder.py 的嵌入模型（模型是公共资源），索引与检索逻辑全部自写。
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根入 path

import config  # noqa: E402
from src.generator import get_generator  # noqa: E402
from src.embedder import get_embedder  # noqa: E402


# ============================================================
# B1：裸模型（无检索增强）
# ============================================================
B1_SYSTEM = """你是一个校园信息问答助手。请直接回答用户的问题。
如果你不确定答案，请如实说明你不确定，不要编造。"""


class BareLLM:
    name = "b1_bare"

    def __init__(self):
        self.generator = get_generator()

    def __call__(self, question: str) -> dict:
        t0 = time.perf_counter()
        res = self.generator.chat(B1_SYSTEM, question, max_tokens=512)
        dt = time.perf_counter() - t0
        return {
            "answer": res["text"],
            "refused": False,          # 裸模型没有拒答机制
            "sources": [],
            "retrieved": [],
            "timing": {"retrieve": 0.0, "judge": 0.0, "generate": dt, "total": dt},
        }


# ============================================================
# B2：朴素 RAG（独立实现）
# ============================================================
_NAIVE_DIR = config.INDEX_DIR / "_eval_naive"   # 独立目录，不污染 recursive 索引
_NAIVE_SIZE = 500                               # 固定长度 500 字符，无重叠

B2_SYSTEM = """你是一个校园信息问答助手。请只依据下面提供的资料回答问题，不要使用你自己的知识。
资料中能找到答案时，依据资料回答，并在结论后标注引用编号 [1]。
资料中没有答案时，请如实说明资料中没有相关信息。"""

B2_USER = """【资料】
[1] {context}

【问题】
{question}

请给出回答，并在依据后标注引用编号 [1]。"""


class NaiveRAG:
    name = "b2_naive"

    def __init__(self):
        self.generator = get_generator()
        self.embedder = get_embedder()
        self.chunks = self._split_fixed()
        self._rec_map = self._load_recursive_map()
        self.index = self._build_index()

    # ---- 固定长度切分（自写，不复用 chunker）----
    def _split_fixed(self) -> list:
        chunks = []
        for p in sorted(config.TEXT_DIR.glob("*.txt")):
            doc_id = p.stem
            text = p.read_text(encoding="utf-8")
            n = 0
            for start in range(0, len(text), _NAIVE_SIZE):
                seg = text[start:start + _NAIVE_SIZE]
                if seg.strip():
                    chunks.append({
                        "chunk_id": f"{doc_id}__nv{n:04d}", "doc_id": doc_id,
                        "text": seg, "char_start": start, "char_end": start + len(seg),
                    })
                    n += 1
        return chunks

    # ---- 把 naive 块映射回标准（recursive）chunk_id，使检索指标可比 ----
    def _load_recursive_map(self) -> dict:
        m = {}
        path = config.CHUNK_DIR / "chunks_recursive.jsonl"
        with open(path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                c = json.loads(line)
                m.setdefault(c["doc_id"], []).append(
                    (c["char_start"], c["char_end"], c["chunk_id"]))
        return m

    def _map_chunk(self, chunk: dict) -> str:
        best, best_ov = "", 0
        for cs, ce, cid in self._rec_map.get(chunk["doc_id"], []):
            ov = min(chunk["char_end"], ce) - max(chunk["char_start"], cs)
            if ov > best_ov:
                best_ov, best = ov, cid
        return best or f"{chunk['doc_id']}__nv"

    # ---- 自建 FAISS 索引 ----
    def _build_index(self):
        import faiss
        import numpy as np

        vecs = np.asarray(self.embedder.encode([c["text"] for c in self.chunks]),
                          dtype=np.float32)
        idx = faiss.IndexFlatIP(self.embedder.dim)
        idx.add(vecs)
        _NAIVE_DIR.mkdir(parents=True, exist_ok=True)
        faiss.write_index(idx, str(_NAIVE_DIR / "faiss.index"))
        with open(_NAIVE_DIR / "meta.json", "w", encoding="utf-8") as f:
            json.dump({
                "baseline": "b2_naive", "chunk_size": _NAIVE_SIZE,
                "num_chunks": len(self.chunks), "dim": self.embedder.dim,
                "chunk_ids": [c["chunk_id"] for c in self.chunks],
            }, f, ensure_ascii=False)
        return idx

    # ---- 自写检索（top-k 稠密）----
    def search(self, query: str, top_k: int = 10) -> list:
        import numpy as np

        qv = np.asarray(self.embedder.encode_query(query), dtype=np.float32).reshape(1, -1)
        k = min(int(top_k), len(self.chunks))
        scores, idxs = self.index.search(qv, k)
        out = []
        for i, s in zip(idxs[0], scores[0]):
            if i < 0:
                continue
            c = self.chunks[int(i)]
            out.append({"chunk_id": self._map_chunk(c), "doc_id": c["doc_id"],
                        "text": c["text"], "score": float(s)})
        return out

    def __call__(self, question: str) -> dict:
        t0 = time.perf_counter()
        hits = self.search(question, top_k=10)   # 检索 top-10（生成只用 top-1）
        t_ret = time.perf_counter() - t0

        top1 = hits[:1]
        t1 = time.perf_counter()
        if top1:
            user = B2_USER.format(context=top1[0]["text"], question=question)
            res = self.generator.chat(B2_SYSTEM, user, max_tokens=512)
            answer = res.get("text", "")
        else:
            answer = "资料中没有相关信息。"
        t_gen = time.perf_counter() - t1

        sources = []
        if top1:
            sources = [{"idx": 1, "chunk_id": top1[0]["chunk_id"], "doc_id": top1[0]["doc_id"],
                        "doc_title": top1[0]["doc_id"], "heading_path": "",
                        "score": top1[0]["score"], "char_start": 0, "char_end": 0,
                        "snippet": top1[0]["text"][:200]}]
        return {
            "answer": answer,
            "refused": False,          # 朴素 RAG 没有拒答机制
            "sources": sources,
            "retrieved": [{"chunk_id": h["chunk_id"], "doc_id": h["doc_id"]} for h in hits],
            "timing": {"retrieve": t_ret, "judge": 0.0, "generate": t_gen,
                       "total": t_ret + t_gen},
        }


# ============================================================
# B3：完整系统（包装 QAPipeline，行为不变）
# ============================================================
class FullSystem:
    name = "b3_full"

    def __init__(self):
        from src.pipeline import QAPipeline
        from src.retriever import get_retriever
        self.pipeline = QAPipeline()
        self.retriever = get_retriever()

    def __call__(self, question: str) -> dict:
        r = self.pipeline.ask(question)
        # 额外检索 top-10 仅用于计算检索指标（不影响生成所用的 top-5）
        top10 = self.retriever.retrieve(question, top_k=10)
        return {
            "answer": r["answer"],
            "refused": r["refused"],
            "sources": r["sources"],
            "retrieved": [{"chunk_id": h["chunk_id"], "doc_id": h["doc_id"]} for h in top10],
            "timing": r["timing"],
        }


# ============================================================
# b3_rerank：完整系统 + Cross-Encoder 重排（唯一变量是"是否有重排"）
# ============================================================
class FullSystemRerank:
    """召回 top-RERANK_TOP_K → 重排 → top_k → 判定 → 生成。

    ★ 除"检索后多一步重排"外，阈值初筛 / 逐块判定 / 拒答守卫 / 引用编号完全不变，
    因此与 b3_full 的对比是干净的消融（唯一自变量 = 重排开关）。
    """

    name = "b3_rerank"

    def __init__(self, top_k=None):
        from src.pipeline import QAPipeline
        from src.retriever import Retriever

        self.retriever = Retriever(use_rerank=True)
        self.pipeline = QAPipeline(top_k=top_k, retriever=self.retriever)

    def __call__(self, question: str) -> dict:
        r = self.pipeline.ask(question)
        all_r = self.retriever.last_reranked_all or []
        retrieved = [{"chunk_id": h["chunk_id"], "doc_id": h["doc_id"]} for h in all_r[:10]]
        timing = dict(r["timing"])
        timing["rerank"] = round(self.retriever.last_rerank_elapsed, 3)
        return {
            "answer": r["answer"],
            "refused": r["refused"],
            "sources": r["sources"],
            "retrieved": retrieved,
            "timing": timing,
        }


class FullSystemRerankTop10(FullSystemRerank):
    """b3_rerank_top10：重排后 top-10 送入判定与生成（对照"多喂资料是否改善判定"）。"""

    name = "b3_rerank_top10"

    def __init__(self):
        super().__init__(top_k=10)


BASELINES = {
    "b1_bare": BareLLM,
    "b2_naive": NaiveRAG,
    "b3_full": FullSystem,
    "b3_rerank": FullSystemRerank,
    "b3_rerank_top10": FullSystemRerankTop10,
}
