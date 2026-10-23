"""reranker.py — Cross-Encoder 重排（BGE-reranker-base，本地加载）

职责：
    - 从【本地路径】加载 bge-reranker-base（禁止运行时联网下载）
    - rerank(query, candidates, top_k)：对候选块逐条打相关性分并重排序
    - ★ 打分文本会【去掉 heading_path 前缀】，避免前缀稀释相关性判断
    - 保留 recall_rank（重排前名次）与 rerank_rank（重排后名次），
      用于测量"重排把答案块提前了多少"

显存有限（8GB），batch_size 默认 16。
"""
import sys
import time
from pathlib import Path

# 项目根入 path（供 `python src/reranker.py` 直接运行单测；作为库模块被导入时幂等无副作用）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根入 path

import config  # noqa: E402


class Reranker:
    def __init__(self, model_path=None, device=None, batch_size=None):
        from sentence_transformers import CrossEncoder

        self.model_path = Path(model_path) if model_path else Path(config.RERANK_MODEL_PATH)
        if device is None:
            device = getattr(config, "RERANK_DEVICE", "cuda")
        if device == "cuda":
            try:
                import torch
                if not torch.cuda.is_available():
                    print("[警告] 请求 device=cuda 但 CUDA 不可用，自动降级为 cpu")
                    device = "cpu"
            except Exception:
                device = "cpu"
        self._device = device
        self.batch_size = batch_size or getattr(config, "RERANK_BATCH_SIZE", 16)

        if not self.model_path.exists():
            raise RuntimeError(
                f"重排模型路径不存在: {self.model_path}"
                f"（请先将模型下载到该本地目录；禁止运行时联网下载）")

        try:
            self._model = CrossEncoder(str(self.model_path), device=device)
        except Exception as e:
            raise RuntimeError(f"重排模型加载失败: {self.model_path} ({e})") from e

        self.last_elapsed = 0.0   # 最近一次 rerank 耗时（秒）

    @property
    def device(self) -> str:
        return self._device

    @staticmethod
    def pair_text(candidate: dict) -> str:
        """打分文本 = 块正文去掉 heading_path 前缀（前缀会稀释相关性判断）。"""
        text = candidate.get("text", "") or ""
        hp = candidate.get("heading_path", "") or ""
        if hp and text.startswith(hp):
            return text[len(hp):].lstrip("\n")
        return text

    def rerank(self, query: str, candidates: list, top_k: int = None) -> list:
        """对候选重排。

        返回按 rerank_score 降序的新列表（浅拷贝原 dict 并新增字段）：
            rerank_score: float   重排分数
            recall_rank : int     重排前在召回列表中的名次（从 1 起）
            rerank_rank : int     重排后的名次（从 1 起）
        candidates 为空时返回 []；top_k=None 返回全部。
        """
        if not candidates:
            self.last_elapsed = 0.0
            return []

        pairs = [(query, self.pair_text(c)) for c in candidates]
        t0 = time.perf_counter()
        scores = self._model.predict(pairs, batch_size=self.batch_size)
        self.last_elapsed = round(time.perf_counter() - t0, 4)

        out = []
        for i, (c, s) in enumerate(zip(candidates, scores), start=1):
            item = dict(c)
            item["rerank_score"] = float(s)
            item["recall_rank"] = i
            out.append(item)
        out.sort(key=lambda x: x["rerank_score"], reverse=True)
        for j, item in enumerate(out, start=1):
            item["rerank_rank"] = j

        return out[:top_k] if top_k is not None else out


_RERANKER = None


def get_reranker() -> Reranker:
    """返回单例 Reranker（照 embedder / generator 的写法）"""
    global _RERANKER
    if _RERANKER is None:
        _RERANKER = Reranker()
    return _RERANKER


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

    print("=" * 78)
    print("Reranker 单测")
    print("=" * 78)

    r = get_reranker()
    print(f"模型: {r.model_path}")
    print(f"设备: {r.device}   批大小: {r.batch_size}\n")

    # ---- [1] 返回列表按 rerank_score 降序 ----
    print("[1] rerank_score 降序")
    cands = [
        {"chunk_id": "a", "text": "今日天气不错，适合出门散步。", "heading_path": "天气"},
        {"chunk_id": "b", "text": "课程考核成绩不及格的学生，可参加学校统一组织的补考。",
         "heading_path": "考试管理规定 > 第四章 补考"},
        {"chunk_id": "c", "text": "图书馆开放时间为每天 8:00 至 22:00。", "heading_path": "图书馆"},
    ]
    out = r.rerank("考试不及格可以补考吗", cands)
    desc = all(out[i]["rerank_score"] >= out[i + 1]["rerank_score"] for i in range(len(out) - 1))
    check("按 rerank_score 降序", desc, True)
    check("长度不变", len(out), 3)
    for it in out:
        print(f"       rerank_rank={it['rerank_rank']} recall_rank={it['recall_rank']} "
              f"score={it['rerank_score']:.4f}  {it['chunk_id']}")

    # ---- [2] recall_rank / rerank_rank 正确（构造"重排后顺序改变"的用例）----
    print("\n[2] recall_rank / rerank_rank（重排后顺序改变）")
    cands2 = [
        {"chunk_id": "x1", "text": "今日天气晴朗，气温适宜。", "heading_path": ""},
        {"chunk_id": "x2", "text": "图书馆每天开放到晚上十点。", "heading_path": ""},
        {"chunk_id": "x3", "text": "课程考核成绩不及格的学生可参加补考。", "heading_path": ""},
    ]
    out2 = r.rerank("考试不及格可以补考吗", cands2)
    print("       重排后顺序: " + " -> ".join(
        f"{it['chunk_id']}(recall={it['recall_rank']},rerank={it['rerank_rank']},"
        f"s={it['rerank_score']:.4f})" for it in out2))
    check("最相关块(x3)排到 rerank_rank=1", out2[0]["chunk_id"], "x3")
    check("x3 的 rerank_rank", out2[0]["rerank_rank"], 1)
    check("x3 的 recall_rank（召回时排第 3）", out2[0]["recall_rank"], 3)
    x1_item = [it for it in out2 if it["chunk_id"] == "x1"][0]
    check("x1 被推后（rerank_rank > recall_rank）",
          x1_item["rerank_rank"] > x1_item["recall_rank"], True)
    check("x1 的 recall_rank 仍为 1", x1_item["recall_rank"], 1)
    check("recall_rank 集合完整", sorted(it["recall_rank"] for it in out2), [1, 2, 3])
    check("rerank_rank 集合完整", sorted(it["rerank_rank"] for it in out2), [1, 2, 3])

    # ---- [3] 空候选 ----
    print("\n[3] 边界：空候选")
    check("返回空列表", r.rerank("任意问题", []), [])

    # ---- [4] 单条候选 ----
    print("\n[4] 边界：单条候选")
    single = r.rerank("任意问题", [{"chunk_id": "s1", "text": "唯一候选文本", "heading_path": ""}])
    check("长度为 1", len(single), 1)
    check("recall_rank == rerank_rank == 1",
          (single[0]["recall_rank"], single[0]["rerank_rank"]), (1, 1))
    check("rerank_score 为 float", isinstance(single[0]["rerank_score"], float), True)

    # ---- [5] 打分文本去掉 heading_path 前缀 ----
    print("\n[5] 打分文本 = 正文（去掉 heading_path 前缀）")
    c = {"chunk_id": "p1", "text": "标题A\n正文B", "heading_path": "标题A"}
    check("pair_text 去前缀", Reranker.pair_text(c), "正文B")
    c2 = {"chunk_id": "p2", "text": "正文B", "heading_path": "不匹配的标题"}
    check("前缀不匹配时原样返回", Reranker.pair_text(c2), "正文B")
    check("无 heading_path 时原样返回",
          Reranker.pair_text({"text": "正文C"}), "正文C")

    # 捕获实际送入模型的 pair，确认用的是去前缀后的文本
    captured = []
    orig_predict = r._model.predict

    def _fake_predict(pairs, **kw):
        captured.extend(pairs)
        return orig_predict(pairs, **kw)

    r._model.predict = _fake_predict
    try:
        r.rerank("问题Q", [{"chunk_id": "p3", "text": "前缀\n真正的正文", "heading_path": "前缀"}])
    finally:
        r._model.predict = orig_predict
    check("送入模型的 query", captured[0][0], "问题Q")
    check("送入模型的候选文本已去前缀", captured[0][1], "真正的正文")

    # ---- [6] top_k 截断 ----
    print("\n[6] top_k 截断")
    check("top_k=2 返回 2 条", len(r.rerank("考试不及格可以补考吗", cands, top_k=2)), 2)
    check("top_k 截断后仍降序",
          [it["chunk_id"] for it in r.rerank("考试不及格可以补考吗", cands, top_k=2)],
          [out[0]["chunk_id"], out[1]["chunk_id"]])

    print("\n" + "=" * 78)
    print(f"单测结果: {passed} passed, {failed} failed")
    print(f"重排耗时（3 条候选）: {r.last_elapsed}s")
    print("=" * 78)
