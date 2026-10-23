"""indexer.py — FAISS 密集向量索引（IndexFlatIP 内积）

块的 text 字段【含 heading_path 前缀】原样编码；检索时 query 走 encode_query()。
向量已 L2 归一化，IndexFlatIP 内积等价余弦相似度。
"""
import json
import time
from datetime import datetime
from pathlib import Path

import config  # noqa: E402
import numpy as np  # noqa: E402
from src import embedder as embedder_module  # noqa: E402


class DenseIndex:
    def __init__(self, dim: int = None):
        self._dim = dim
        self._index = None
        self._chunk_map = {}
        self._embedder = None

    @classmethod
    def build(cls, chunks: list, embedder=None, out_dir: Path = None,
              strategy: str = "recursive", source_jsonl: str = None) -> "DenseIndex":
        """编码 chunk 的 text 字段（含前缀，原样编码），建 FAISS 索引并落盘。"""
        import faiss

        emb = embedder or embedder_module.get_embedder()
        if out_dir is None:
            out_dir = config.INDEX_DIR / strategy
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        t0 = time.perf_counter()
        texts = [c["text"] for c in chunks]
        vectors = np.asarray(emb.encode(texts, normalize=True), dtype=np.float32)

        dim = emb.dim
        index = faiss.IndexFlatIP(dim)
        index.add(vectors)

        faiss.write_index(index, str(out_dir / "faiss.index"))
        chunk_map = {str(i): c["chunk_id"] for i, c in enumerate(chunks)}
        with open(out_dir / "chunk_map.json", "w", encoding="utf-8") as f:
            json.dump(chunk_map, f, ensure_ascii=False, indent=2)

        build_seconds = round(time.perf_counter() - t0, 3)
        if source_jsonl is None:
            source_jsonl = f"data/chunks/chunks_{strategy}.jsonl"
        build_info = {
            "strategy": strategy,
            "embed_model": config.EMBED_MODEL_NAME,
            "embed_device": emb.device,
            "dim": dim,
            "num_chunks": len(chunks),
            "index_type": "IndexFlatIP",
            "metric": "inner_product(cosine)",
            "query_prefix_used": True,
            "query_instruction": embedder_module.QUERY_INSTRUCTION,
            "source_jsonl": source_jsonl,
            "chunk_params": {"target_min": 400, "target_max": 600, "hard_max": 800},
            "built_at": datetime.now().isoformat(),
            "build_seconds": build_seconds,
        }
        with open(out_dir / "build_info.json", "w", encoding="utf-8") as f:
            json.dump(build_info, f, ensure_ascii=False, indent=2)

        obj = cls(dim=dim)
        obj._index = index
        obj._chunk_map = chunk_map
        obj._embedder = emb
        return obj

    @classmethod
    def load(cls, index_dir: Path = None, strategy: str = "recursive") -> "DenseIndex":
        import faiss

        if index_dir is None:
            index_dir = config.INDEX_DIR / strategy
        index_dir = Path(index_dir)
        index = faiss.read_index(str(index_dir / "faiss.index"))
        with open(index_dir / "chunk_map.json", "r", encoding="utf-8") as f:
            chunk_map = json.load(f)
        obj = cls(dim=index.d)
        obj._index = index
        obj._chunk_map = chunk_map
        obj._embedder = embedder_module.get_embedder()
        return obj

    def search(self, query: str, top_k: int = 20, use_query_prefix: bool = True) -> list:
        """检索，返回 [{"chunk_id","score","rank"}]，按分数降序。"""
        emb = self._embedder or embedder_module.get_embedder()
        if use_query_prefix:
            qv = emb.encode_query(query)
        else:
            qv = emb.encode(query)
        qv = np.asarray(qv, dtype=np.float32).reshape(1, -1)

        k = min(int(top_k), self.size)
        if k <= 0:
            return []
        scores, indices = self._index.search(qv, k)
        results = []
        for rank, (idx, score) in enumerate(zip(indices[0], scores[0])):
            chunk_id = self._chunk_map.get(str(int(idx)), str(int(idx)))
            results.append({"chunk_id": chunk_id, "score": float(score), "rank": rank})
        return results

    @property
    def size(self) -> int:
        return int(self._index.ntotal) if self._index is not None else 0

    @property
    def dim(self) -> int:
        return int(self._index.d) if self._index is not None else self._dim


_INDEXES = {}


def get_index(strategy: str = "recursive") -> DenseIndex:
    """返回单例 DenseIndex（按 strategy 缓存，避免重复加载）"""
    if strategy not in _INDEXES:
        _INDEXES[strategy] = DenseIndex.load(strategy=strategy)
    return _INDEXES[strategy]
