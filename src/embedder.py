"""embedder.py — BGE 嵌入模型封装

职责：
    - 加载本地 BGE-small-zh-v1.5 模型（512 维）
    - encode() 对【文档】直接编码（不加前缀）
    - encode_query() 对【查询】加 BGE 检索指令前缀后编码
    - 向量 L2 归一化（配合 FAISS 内积检索）
"""
from pathlib import Path

import config  # noqa: E402

import numpy as np  # noqa: E402

# BGE 中文模型的查询指令前缀（检索任务必须加在 query 前，文档不加）
QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："


class Embedder:
    def __init__(self, model_path=None, device=None, batch_size=32):
        import torch
        from sentence_transformers import SentenceTransformer

        self.model_path = Path(model_path) if model_path else Path(config.EMBED_MODEL_PATH)
        if device is None:
            device = config.EMBED_DEVICE
        if device == "cuda" and not torch.cuda.is_available():
            print(f"[警告] 请求 device=cuda 但 CUDA 不可用，自动降级为 cpu")
            device = "cpu"
        self._device = device
        self.batch_size = batch_size
        try:
            self._model = SentenceTransformer(str(self.model_path), device=device)
        except Exception as e:
            raise RuntimeError(f"嵌入模型加载失败: {self.model_path} ({e})") from e

    @property
    def dim(self) -> int:
        """向量维度（BGE-small-zh-v1.5 为 512）"""
        return int(self._model.get_embedding_dimension())

    @property
    def device(self) -> str:
        """实际使用的设备（"cuda" 或 "cpu"）"""
        return self._device

    def encode(self, texts, batch_size=None, normalize=True, show_progress=False):
        """编码文本为向量。

        - texts 为 str 时返回一维 ndarray (512,)
        - texts 为 list 时返回二维 ndarray (N, 512)
        - normalize=True 时做 L2 归一化
        - 类型固定 np.float32；空列表返回 (0, 512)
        """
        single = isinstance(texts, str)
        if single:
            texts = [texts]
        if len(texts) == 0:
            return np.zeros((0, self.dim), dtype=np.float32)

        bs = batch_size or self.batch_size
        vecs = self._model.encode(
            texts,
            batch_size=bs,
            normalize_embeddings=normalize,
            show_progress_bar=show_progress,
            convert_to_numpy=True,
        )
        vecs = np.asarray(vecs, dtype=np.float32)
        return vecs[0] if single else vecs

    def encode_query(self, query: str) -> np.ndarray:
        """对【查询】加 BGE 检索指令前缀后编码（文档编码请直接用 encode）"""
        return self.encode(QUERY_INSTRUCTION + query)

    def similarity(self, a, b) -> float:
        """计算两个向量的余弦相似度（已归一化时等价于直接点积）"""
        a = np.asarray(a, dtype=np.float32).ravel()
        b = np.asarray(b, dtype=np.float32).ravel()
        denom = float(np.linalg.norm(a) * np.linalg.norm(b))
        if denom == 0:
            return 0.0
        return float(np.dot(a, b) / denom)


# 模块级单例，避免重复加载模型
_EMBEDDER = None


def get_embedder() -> Embedder:
    """返回单例 Embedder"""
    global _EMBEDDER
    if _EMBEDDER is None:
        _EMBEDDER = Embedder()
    return _EMBEDDER


if __name__ == "__main__":
    import time

    print("=" * 72)
    print("BGE 嵌入模型自测")
    print("=" * 72)

    t0 = time.perf_counter()
    emb = Embedder()
    t_load = time.perf_counter() - t0
    print(f"模型路径: {emb.model_path}")
    print(f"设备: {emb.device}")
    print(f"向量维度: {emb.dim}")
    print(f"加载耗时: {t_load:.3f}s")

    t1 = time.perf_counter()
    v = emb.encode("校园问答系统的检索增强生成")
    t_enc1 = time.perf_counter() - t1
    print(f"单句编码: shape={v.shape}, dtype={v.dtype}, 耗时={t_enc1:.3f}s")

    sents = ["学生的选课流程是怎样的", "如何办理选课手续", "今天天气不错"]
    t2 = time.perf_counter()
    vecs = emb.encode(sents)
    t_enc2 = time.perf_counter() - t2
    print(f"3 句编码: shape={vecs.shape}, 耗时={t_enc2:.3f}s")
    print("相似度矩阵（两两余弦）:")
    for i in range(len(sents)):
        row = [f"{emb.similarity(vecs[i], vecs[j]):.4f}" for j in range(len(sents))]
        print(f"  [{', '.join(row)}]")

    empty = emb.encode([])
    print(f"空列表编码: shape={empty.shape}, dtype={empty.dtype}")

    print()
    print("=" * 72)
    print("encode_query 前缀生效验证")
    print("=" * 72)
    docs = emb.encode(["学生的选课流程是怎样的", "今天天气不错"])
    q_no = emb.encode("选课流程")
    q_with = emb.encode_query("选课流程")

    sim_no_rel = emb.similarity(q_no, docs[0])
    sim_no_irr = emb.similarity(q_no, docs[1])
    sim_with_rel = emb.similarity(q_with, docs[0])
    sim_with_irr = emb.similarity(q_with, docs[1])

    print("不加前缀 query='选课流程':")
    print(f"  与「学生的选课流程是怎样的」相似度: {sim_no_rel:.4f}")
    print(f"  与「今天天气不错」相似度:           {sim_no_irr:.4f}")
    print("加前缀 query（encode_query）:")
    print(f"  与「学生的选课流程是怎样的」相似度: {sim_with_rel:.4f}")
    print(f"  与「今天天气不错」相似度:           {sim_with_irr:.4f}")

    d_no = sim_no_rel - sim_no_irr
    d_with = sim_with_rel - sim_with_irr
    print(f"区分度（相关-不相关）: 不加前缀={d_no:.4f}, 加前缀={d_with:.4f}")
    print("=" * 72)
