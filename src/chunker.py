"""chunker.py — 递归结构感知切分（本轮只实现这一种策略）

切分依据 Markdown 标题逐级下降：
  第1级 按 "# "（章）→ 第2级 按 "## "（节/条）→ 第3级 按 "### "（条）
  → 第4级 按空行 → 第5级 按中文句末标点 → 第6级 按 hard_max 硬切

每个 chunk 的 text 字段 = heading_path + "\\n" + 正文；char_start/char_end
指向正文在【原始 text】中的偏移（不含前缀）。
"""
import re
from datetime import datetime
from pathlib import Path

import config  # noqa: E402
from src import utils  # noqa: E402

logger = utils.get_logger("chunker")

_ARTICLE_NO_RE = re.compile(r"^(第[一二三四五六七八九十百千零]+条)")
_SENTENCE_RE = re.compile(r"[。；！？]")
_PARAGRAPH_RE = re.compile(r"\n\s*\n")

# chunk dict 必备字段（用于完整性检查）
REQUIRED_FIELDS = [
    "chunk_id", "doc_id", "chunk_index", "text", "heading_path",
    "token_len", "char_start", "char_end", "content_type", "strategy", "created_at",
]


def build_heading_path(doc_title: str, h1: str = "", h2: str = "") -> str:
    """用 ' > ' 连接文档标题与各层级标题（空段跳过）"""
    parts = [doc_title]
    if h1:
        parts.append(h1)
    if h2:
        parts.append(h2)
    return " > ".join(parts)


def _heading_display(htext: str) -> str:
    """从标题行内容构造 heading 段。

    「第X条」后若跟简短主题（≤15 字）则一并保留，否则只保留条号，
    避免把正文开头误当成标题塞进 heading_path。
    """
    m = _ARTICLE_NO_RE.match(htext)
    if m:
        no = m.group(1)
        rest = htext[len(no):].strip()
        if rest and len(rest) <= 15:
            return f"{no} {rest}"
        return no
    return htext


def _token_len(text: str, start: int, end: int) -> int:
    return utils.estimate_tokens(text[start:end])


def _trim_interval(text: str, start: int, end: int):
    """去掉 [start, end) 前后的换行/空格，返回精确偏移"""
    while start < end and text[start] in "\n ":
        start += 1
    while end > start and text[end - 1] in "\n ":
        end -= 1
    return start, end


def _find_headings(text, start, end, level):
    prefix = "#" * level
    pat = re.compile(rf"^{prefix}[ \t]+[^\n]*", re.MULTILINE)
    return list(pat.finditer(text, start, end))


def _is_real_heading(htext: str) -> bool:
    """判断是否为真正的标题：以冒号结尾的行是正文引导句（如"第六条 成绩填报及试卷查阅："），
    后面跟着（一）（二）列表，不是标题。"""
    s = htext.strip()
    return not (s.endswith("：") or s.endswith(":"))


def _split_by_heading(text, start, end, level, heading_parts):
    """按 level 级标题切分 [start, end)，返回 [(start, end, new_heading_parts)]"""
    matches = _find_headings(text, start, end, level)
    # 过滤掉以冒号结尾的"标题"（实为正文引导句）
    matches = [m for m in matches if _is_real_heading(m.group(0).lstrip("#").strip())]
    if not matches:
        return []

    pieces = []
    # 第一个标题前的内容（继承父级 heading_parts）
    if matches[0].start() > start:
        ps, pe = _trim_interval(text, start, matches[0].start())
        if pe > ps:
            pieces.append((ps, pe, list(heading_parts)))

    for k, m in enumerate(matches):
        htext = m.group(0).lstrip("#").strip()
        new_parts = heading_parts[:level - 1] + [_heading_display(htext)]
        bs, be = m.end(), (matches[k + 1].start() if k + 1 < len(matches) else end)
        bs, be = _trim_interval(text, bs, be)
        if be > bs:
            pieces.append((bs, be, new_parts))
    return pieces


def _split_by_paragraphs(text, start, end):
    """按空行切分，返回 [(start, end)]"""
    pieces, pos = [], start
    for m in _PARAGRAPH_RE.finditer(text, start, end):
        if m.start() > pos:
            pieces.append((pos, m.start()))
        pos = m.end()
    if pos < end:
        pieces.append((pos, end))
    return pieces


def _split_by_sentences(text, start, end):
    """按中文句末标点切分（切分点在标点之后），返回 [(start, end)]"""
    pieces, pos = [], start
    for m in _SENTENCE_RE.finditer(text, start, end):
        cut = m.end()
        if cut > pos:
            pieces.append((pos, cut))
        pos = cut
    if pos < end:
        pieces.append((pos, end))
    return pieces


def _hard_split(text, start, end, hard_max):
    """按 hard_max 字符硬切（中文 1 字≈1 token），返回 [(start, end)]"""
    pieces, pos = [], start
    while pos < end:
        cut = min(pos + hard_max, end)
        pieces.append((pos, cut))
        pos = cut
    return pieces


def _recursive_split(text, start, end, heading_parts, level, target_max, hard_max):
    """递归切分 [start, end)，level 决定切分方式：
    1/2/3=标题层级，4=空行，5=句子，6=硬切"""
    if _token_len(text, start, end) <= target_max:
        return [(start, end, list(heading_parts))]

    if level >= 6:
        logger.warning("单块超过 hard_max=%d，按 hard_max 硬切", hard_max)
        return [(s, e, list(heading_parts)) for s, e in _hard_split(text, start, end, hard_max)]

    if level <= 3:
        pieces = _split_by_heading(text, start, end, level, heading_parts)
    elif level == 4:
        pieces = [(s, e, list(heading_parts)) for s, e in _split_by_paragraphs(text, start, end)]
    else:
        pieces = [(s, e, list(heading_parts)) for s, e in _split_by_sentences(text, start, end)]

    if len(pieces) <= 1:
        # 切不动，降级到下一级
        return _recursive_split(text, start, end, heading_parts, level + 1, target_max, hard_max)

    result = []
    for s, e, new_parts in pieces:
        result.extend(_recursive_split(text, s, e, new_parts, level + 1, target_max, hard_max))
    return result


def _common_prefix(a, b):
    i = 0
    while i < len(a) and i < len(b) and a[i] == b[i]:
        i += 1
    return a[:i]


def _merge_intervals(intervals, text, target_min, target_max, hard_max):
    """自底向上合并相邻块（向前看贪心）。

    规则 a：从当前块开始，尽量把相邻块合并到纯正文 token 之和 <= target_max；
    规则 b：若合并结果 < target_min（碎片），再并入下一块，只要和 <= hard_max；
    合并后 heading_path 取所有被并入块的公共前缀，char 区间取最小起点/最大终点
    （覆盖被跳过的标题行，保证 text[char_start:char_end] 覆盖合并后的正文）。

    判断用「纯正文 token 之和」（不含被跳过的标题行），避免标题行累积撑大块。
    """
    if not intervals:
        return []
    tokens = [_token_len(text, s, e) for s, e, _ in intervals]
    n = len(intervals)
    merged = []
    i = 0
    while i < n:
        j = i
        acc = 0
        while j < n and acc + tokens[j] <= target_max:  # 规则 a
            acc += tokens[j]
            j += 1
        if acc < target_min and j < n and acc + tokens[j] <= hard_max:  # 规则 b
            acc += tokens[j]
            j += 1
        # 合并 [i, j)
        s = intervals[i][0]
        e = intervals[j - 1][1]
        parts = intervals[i][2]
        for k in range(i + 1, j):
            parts = _common_prefix(parts, intervals[k][2])
        merged.append([s, e, parts])
        i = j
    return merged


def chunk_document(doc_id: str, text: str, meta: dict = None,
                   target_min: int = None, target_max: int = None,
                   hard_max: int = None) -> list:
    """把清洗后的文本切成检索块，返回 chunk dict 列表"""
    if target_min is None:
        target_min = config.CHUNK_TARGET_MIN
    if target_max is None:
        target_max = config.CHUNK_TARGET_MAX
    if hard_max is None:
        hard_max = config.CHUNK_HARD_MAX
    doc_title = (meta or {}).get("title", doc_id)
    created_at = datetime.now().isoformat()
    if not text or not text.strip():
        return []

    intervals = _recursive_split(text, 0, len(text), [], 1, target_max, hard_max)
    intervals = _merge_intervals(intervals, text, target_min, target_max, hard_max)

    chunks = []
    for i, (start, end, heading_parts) in enumerate(intervals):
        body = text[start:end]
        if not body.strip():
            continue
        heading_path = " > ".join([doc_title] + heading_parts)
        chunk_text = heading_path + "\n" + body
        chunks.append({
            "chunk_id": f"{doc_id}_{i + 1:04d}",
            "doc_id": doc_id,
            "chunk_index": i,
            "text": chunk_text,
            "heading_path": heading_path,
            "token_len": utils.estimate_tokens(body),
            "char_start": start,
            "char_end": end,
            "content_type": "text",
            "strategy": "recursive",
            "created_at": created_at,
        })
    return chunks


def load_documents(text_dir, meta_csv) -> list:
    """读取 text_dir 下所有 txt，关联 documents.csv 元数据，
    返回 [(doc_id, text, meta)]"""
    import csv

    meta = {}
    if meta_csv and Path(meta_csv).exists():
        with open(meta_csv, "r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                meta[row.get("doc_id", "")] = row

    docs = []
    for txt in sorted(Path(text_dir).glob("*.txt")):
        doc_id = txt.stem
        text = txt.read_text(encoding="utf-8")
        docs.append((doc_id, text, meta.get(doc_id, {})))
    return docs


if __name__ == "__main__":
    import random
    import time

    docs = load_documents(config.TEXT_DIR, config.META_CSV)
    target = next((d for d in docs if d[0] == "xjgl_2025"), docs[0])
    doc_id, text, meta = target

    t0 = time.perf_counter()
    chunks = chunk_document(doc_id, text, meta)
    elapsed = time.perf_counter() - t0

    lens = [c["token_len"] for c in chunks]
    field_ok = all(all(k in c for k in REQUIRED_FIELDS) for c in chunks)

    print("=" * 72)
    print(f"递归切分自测: {doc_id}")
    print(f"总块数: {len(chunks)}")
    print(f"平均 token: {sum(lens) // len(lens) if lens else 0}")
    print(f"最长: {max(lens) if lens else 0}  最短: {min(lens) if lens else 0}")
    print(f"字段完整性: {'齐全' if field_ok else '缺失'}")
    print(f"耗时: {elapsed:.3f}s")

    print("\n前 3 块:")
    for c in chunks[:3]:
        print(f"  heading_path: {c['heading_path']}")
        print(f"  text 前 120 字: {c['text'][:120]}")
        print()

    print("char_start/char_end 还原验证（随机 5 块）:")
    sample = random.sample(chunks, min(5, len(chunks)))
    for c in sample:
        ok = text[c["char_start"]:c["char_end"]] in c["text"]
        print(f"  {c['chunk_id']}: {'OK' if ok else 'FAIL'}")

    dist = {"<400": 0, "400-600": 0, "600-800": 0, ">800": 0}
    for c in chunks:
        t = c["token_len"]
        if t < 400:
            dist["<400"] += 1
        elif t <= 600:
            dist["400-600"] += 1
        elif t <= 800:
            dist["600-800"] += 1
        else:
            dist[">800"] += 1
    print(f"\ntoken 分布: <400: {dist['<400']}  400-600: {dist['400-600']}  "
          f"600-800: {dist['600-800']}  >800: {dist['>800']}")
    print("=" * 72)
