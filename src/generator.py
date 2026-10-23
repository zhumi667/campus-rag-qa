"""generator.py — 调用本地 Ollama 生成回答（非流式 + 流式）"""
import json
import re
import sys
import time

import config  # noqa: E402
import requests  # noqa: E402
from src import prompts  # noqa: E402


class ContextOverflowError(RuntimeError):
    """请求 token 数超过 num_ctx（Ollama HTTP 400 且含 exceeds the available context size）。

    消息形如 "4175 > 4096"，便于上层打印降级重试日志与决策。
    """

    def __init__(self, raw: str):
        self.raw = raw
        m = re.search(r"\((\d+)\s*tokens\).*?\((\d+)\s*tokens\)", raw, re.S)
        self.requested = int(m.group(1)) if m else None
        self.available = int(m.group(2)) if m else None
        msg = (f"{self.requested} > {self.available}"
               if self.requested is not None and self.available is not None
               else raw[:160])
        super().__init__(msg)


class Generator:
    def __init__(self, model=None, base_url=None, timeout=300):
        self.model = model or config.OLLAMA_MODEL
        self.base_url = base_url or config.OLLAMA_URL
        self.timeout = timeout

    def health(self) -> dict:
        """GET /api/tags，返回 {"ok","models","message"}，连不上时不抛异常。"""
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if r.status_code == 200:
                data = r.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                return {"ok": True, "models": models, "message": "ok"}
            return {"ok": False, "models": [], "message": f"HTTP {r.status_code}"}
        except Exception as e:
            return {"ok": False, "models": [], "message": str(e)}

    def chat(self, system: str, user: str,
             temperature: float = 0.1, num_ctx: int = 4096,
             max_tokens: int = None) -> dict:
        """POST /api/chat（stream=False），返回 text/elapsed/prompt_tokens/completion_tokens。"""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"temperature": temperature, "num_ctx": num_ctx},
        }
        if max_tokens is not None:
            payload["options"]["num_predict"] = max_tokens

        t0 = time.perf_counter()
        try:
            r = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout)
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Ollama 请求失败: {e}") from e

        if r.status_code != 200:
            raise RuntimeError(f"Ollama HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        elapsed = round(time.perf_counter() - t0, 3)
        return {
            "text": data.get("message", {}).get("content", ""),
            "elapsed": elapsed,
            "prompt_tokens": data.get("prompt_eval_count", 0) or 0,
            "completion_tokens": data.get("eval_count", 0) or 0,
        }

    def answer(self, question: str, context_block: str, max_tokens: int = 512) -> dict:
        """用 QA_SYSTEM_PROMPT + QA_USER_TEMPLATE 生成回答，附加 prompt 字段便于调试。

        max_tokens 默认 512：实测 Ollama 不设 num_predict 时，复杂上下文下模型会
        过早停止（只输出引用编号），设一个上限能保证生成完整回答。
        """
        user = prompts.QA_USER_TEMPLATE.format(context=context_block, question=question)
        try:
            res = self.chat(prompts.QA_SYSTEM_PROMPT, user, max_tokens=max_tokens)
        except RuntimeError as e:
            if "exceeds the available context size" in str(e):
                raise ContextOverflowError(str(e)) from e
            raise
        res["prompt"] = user
        return res

    def chat_stream(self, system: str, user: str, temperature: float = 0.1,
                    num_ctx: int = 4096, max_tokens: int = None):
        """流式调用 Ollama /api/chat（stream=True），逐段 yield 文本增量(str)。"""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": True,
            "options": {"temperature": temperature, "num_ctx": num_ctx},
        }
        if max_tokens is not None:
            payload["options"]["num_predict"] = max_tokens

        try:
            r = requests.post(f"{self.base_url}/api/chat", json=payload,
                              stream=True, timeout=self.timeout)
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Ollama 请求失败: {e}") from e

        if r.status_code != 200:
            # 与 answer() 保持一致：流式路径同样要把"超出上下文"识别为 ContextOverflowError，
            # 否则上层无法区分"上下文过长"与"其他服务故障"，也就无法降级重试。
            if "exceeds the available context size" in r.text:
                raise ContextOverflowError(r.text[:200])
            raise RuntimeError(f"Ollama HTTP {r.status_code}: {r.text[:200]}")

        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if data.get("done"):
                break
            piece = data.get("message", {}).get("content", "")
            if piece:
                yield piece

    def answer_stream(self, question: str, context_block: str, max_tokens: int = 512):
        """用 QA_SYSTEM_PROMPT + QA_USER_TEMPLATE 组装后流式生成，逐段 yield 文本。

        ★ chat_stream 是生成器函数，请求体直到【首次迭代】才真正发出，
          因此 HTTP 400 会在迭代过程中抛出。这里统一转成 ContextOverflowError，
          使流式与非流式路径的异常语义一致（上层据此降档或友好提示）。
        """
        user = prompts.QA_USER_TEMPLATE.format(context=context_block, question=question)
        try:
            yield from self.chat_stream(prompts.QA_SYSTEM_PROMPT, user, max_tokens=max_tokens)
        except RuntimeError as e:
            if "exceeds the available context size" in str(e):
                raise ContextOverflowError(str(e)) from e
            raise


_GENERATOR = None


def get_generator() -> Generator:
    global _GENERATOR
    if _GENERATOR is None:
        _GENERATOR = Generator()
    return _GENERATOR


if __name__ == "__main__":
    # 自测用调试小模型（快）；生产用 config.OLLAMA_MODEL = qwen2.5-3b-q4
    g = Generator(model=config.DEBUG_MODEL)
    print(f"自测模型: {config.DEBUG_MODEL}（生产用 {config.OLLAMA_MODEL}）")

    h = g.health()
    print(f"health: ok={h['ok']} models={h['models']} message={h['message']}")
    if not h["ok"]:
        print("Ollama 服务不可用，无法继续自测。请先启动 Ollama（ollama serve）。")
        sys.exit(1)

    context_block = """[1] 来源：桂林电子科技大学考试管理规定（第四章 学生参加考核条件及缓考、补考细则）
课程考核成绩不及格的学生，可参加学校统一组织的补考。补考成绩按实际得分记载，并标注"补考"字样。补考仍不及格者，应重修该课程。"""

    print("\n" + "=" * 60)
    print("有依据问题: 考试不及格可以补考吗")
    print("=" * 60)
    r1 = g.answer("考试不及格可以补考吗", context_block)
    print(r1["text"])
    print(f"耗时 {r1['elapsed']}s  提示tokens={r1['prompt_tokens']}  生成tokens={r1['completion_tokens']}")

    print("\n" + "=" * 60)
    print("无依据问题: 奖学金怎么申请")
    print("=" * 60)
    r2 = g.answer("奖学金怎么申请", context_block)
    print(r2["text"])
    print(f"耗时 {r2['elapsed']}s  提示tokens={r2['prompt_tokens']}  生成tokens={r2['completion_tokens']}")
