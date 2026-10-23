"""utils.py — 通用工具

包含：计时装饰器、日志配置、JSONL 读写、中文文本清洗、中文字数统计。
"""
import functools
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Iterable, List, Optional

import config  # noqa: E402


# ============================================================
# 计时装饰器
# ============================================================
def _append_timing(line: str) -> None:
    """把耗时记录追加写入 logs/timing.md（写失败不影响主流程）"""
    try:
        config.TIMING_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(config.TIMING_FILE, "a", encoding="utf-8") as f:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"- {ts}  {line}\n")
    except OSError:
        pass


def timed(tag: Optional[str] = None):
    """计时装饰器：打印函数耗时，并追加写入 logs/timing.md

    用法：
        @timed()               # 用函数全名作为标签
        @timed("切分")          # 自定义标签
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                elapsed = time.perf_counter() - start
                label = tag if tag else f"{func.__module__}.{func.__name__}"
                line = f"[{label}] 耗时 {elapsed:.3f}s"
                print(line)
                _append_timing(line)

        return wrapper

    return decorator


# ============================================================
# 日志配置
# ============================================================
def get_logger(name: str = "campus_rag", level: int = logging.INFO) -> logging.Logger:
    """返回一个 logger 对象，同时输出到控制台和文件（logs/app.log，UTF-8）

    用法：
        logger = utils.get_logger(__name__)
        logger.info("...")
    """
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(name)
    if not logger.handlers:  # 避免重复添加 handler
        logger.setLevel(level)
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(fmt)
        logger.addHandler(console)

        file_handler = logging.FileHandler(config.LOG_FILE, encoding="utf-8")
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)

        logger.propagate = False
    return logger


# ============================================================
# JSONL 读写
# ============================================================
def read_jsonl(path) -> List[dict]:
    """读取 JSONL 文件，每行一个 JSON 对象"""
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def write_jsonl(path, items: Iterable[dict], append: bool = False) -> None:
    """把 dict 列表写入 JSONL 文件（默认覆盖，append=True 时追加）"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with open(path, mode, encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


# ============================================================
# 中文文本清洗
# ============================================================
# 页眉页脚 / 独立页码行
_PAGE_DASH_RE = re.compile(r"^[—–\-]*\s*\d+\s*[—–\-]*$")   # "— 1 —"、"—1—"
_PAGE_CN_RE = re.compile(r"^第\s*\d+\s*页\s*[，,。.]?\s*$")   # "第 1 页"
_PAGE_EN_RE = re.compile(r"^Page\s*\d+\s*(of\s*\d+)?\s*$", re.IGNORECASE)  # "Page 1"
_PAGE_SLASH_RE = re.compile(r"^\d+\s*/\s*\d+$")             # "1/16"（当前页/总页数）

_CN_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")

# 半角英文标点 -> 中文全角标点（仅当处于中文语境时才转换）
_HALF_TO_FULL_PUNCT = {
    ",": "，",
    ".": "。",
    ";": "；",
    ":": "：",
    "?": "？",
    "!": "！",
    "(": "（",
    ")": "）",
}


def _is_cjk_char(ch: str) -> bool:
    """判断单个字符是否为 CJK 统一表意文字"""
    return "\u4e00" <= ch <= "\u9fff"


def _normalize_fullwidth(text: str) -> str:
    """全角空格→半角；全角字母数字→半角；全角标点（，。；：、（）《》等）原样保留"""
    out = []
    for ch in text:
        code = ord(ch)
        if code == 0x3000:                 # 全角空格 -> 半角空格
            out.append(" ")
        elif (0xFF10 <= code <= 0xFF19     # 全角数字 ０-９
              or 0xFF21 <= code <= 0xFF3A  # 全角大写 Ａ-Ｚ
              or 0xFF41 <= code <= 0xFF5A):  # 全角小写 ａ-ｚ
            out.append(chr(code - 0xFEE0))
        else:
            out.append(ch)  # 全角标点等其他字符保持不变
    return "".join(out)


def _normalize_halfwidth_punct(text: str) -> str:
    """把中文语境中的半角英文标点统一为全角（前后有汉字即视为中文语境）

    特例：句点「.」前是数字且后紧跟非空白字符时，视为序号/小数（如 1. 3.5），
    保持不转换；真正的句末句点（中文语境）仍转为「。」。
    """
    out = []
    n = len(text)
    for i, ch in enumerate(text):
        if ch in _HALF_TO_FULL_PUNCT:
            # 句点特判：数字后跟非空白字符 -> 序号/小数，不转换
            if ch == ".":
                prev_digit = i > 0 and text[i - 1].isdigit()
                next_nonspace = i + 1 < n and not text[i + 1].isspace()
                if prev_digit and next_nonspace:
                    out.append(ch)
                    continue
            prev_cjk = i > 0 and _is_cjk_char(text[i - 1])
            next_cjk = i + 1 < n and _is_cjk_char(text[i + 1])
            if prev_cjk or next_cjk:
                out.append(_HALF_TO_FULL_PUNCT[ch])
                continue
        out.append(ch)
    return "".join(out)


def clean_text(text: str) -> str:
    """中文文本清洗：
    1. 全角空格、全角字母数字统一为半角（全角标点原样保留）
    2. 中文语境中的半角英文标点统一为全角
    3. 去掉页眉页脚 / 独立页码行
    4. 压缩 3 个以上连续换行为单个空行
    """
    if not text:
        return ""
    text = _normalize_fullwidth(text)
    text = _normalize_halfwidth_punct(text)

    lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            lines.append("")  # 保留空行用于分隔段落
            continue
        if (_PAGE_DASH_RE.match(stripped)
                or _PAGE_CN_RE.match(stripped)
                or _PAGE_EN_RE.match(stripped)
                or _PAGE_SLASH_RE.match(stripped)):
            continue  # 丢弃页码/页眉行
        lines.append(stripped)

    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)  # 去多余空行
    return cleaned.strip()


# ============================================================
# 中文字数统计
# ============================================================
def count_chinese(text: str) -> int:
    """统计中文字符数（仅 CJK 统一表意文字）"""
    return len(_CN_CHAR_RE.findall(text or ""))


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数：中文每字约 1 token，英文每词约 1 token（仅用于预估）"""
    cn = len(_CN_CHAR_RE.findall(text or ""))
    en_words = len(re.findall(r"[A-Za-z0-9]+", text or ""))
    return cn + en_words
