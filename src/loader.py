"""loader.py — 文档加载

支持 PDF / DOCX / HTML / TXT 四类文档。
关键点：docx 必须同时遍历 paragraphs 和 tables（已知有文档文字全在表格里）。
表格内容统一转成 "表头: 值" 形式的文本行，并标注 content_type="table"。
解析失败抛出 DocumentLoadError（附带文件名），不静默返回空。
"""
import re
from pathlib import Path
from typing import List, Optional

import config  # noqa: E402
from src import utils  # noqa: E402


# ============================================================
# 异常
# ============================================================
class DocumentLoadError(Exception):
    """文档解析失败异常，message 中必须包含文件名"""


# ============================================================
# 统一返回结构
# ============================================================
class ParsedDocument:
    """解析后的文档对象

    paragraphs: 有序段落列表，每项为 {"index": int, "text": str, "content_type": str}
                content_type ∈ {"text", "table"}，保持原文档顺序。
    """

    def __init__(self, path: str, file_type: str,
                 paragraphs: List[dict], pages: Optional[int] = None):
        self.path = path
        self.file_type = file_type
        self.paragraphs = paragraphs
        self.pages = pages

    @property
    def text_paragraphs(self) -> List[dict]:
        return [p for p in self.paragraphs if p["content_type"] == "text"]

    @property
    def table_paragraphs(self) -> List[dict]:
        return [p for p in self.paragraphs if p["content_type"] == "table"]

    @property
    def full_text(self) -> str:
        return "\n".join(p["text"] for p in self.paragraphs if p["text"])

    def __repr__(self) -> str:
        return (f"ParsedDocument(file={Path(self.path).name!r}, "
                f"type={self.file_type!r}, pages={self.pages}, "
                f"text_paras={len(self.text_paragraphs)}, "
                f"table_paras={len(self.table_paragraphs)})")


# ============================================================
# 表格转文本
# ============================================================
# 属性名关键词（用于判断"横向属性表"：第一列是否为属性名标签）
_ATTR_KEYWORDS = (
    "代码", "名称", "学分", "学时", "学期", "类别", "性质", "部门",
    "对象", "标准", "条件", "时间", "地点", "备注", "编号", "序号",
)


def _clean_cell(c) -> str:
    """清洗单元格：合并单元格内换行、压缩空白，避免竖排/折行文字被切成单字碎片"""
    if c is None:
        return ""
    s = str(c)
    s = re.sub(r"\r?\n", "", s)          # 去掉单元格内换行（竖排文字/折行表头）
    s = re.sub(r"[ \t\u3000]+", " ", s)  # 压缩连续空白为单个空格
    return s.strip()


def _looks_like_attr_label(s: str) -> bool:
    """判断单元格文本是否像"属性名"短标签"""
    if not s or len(s) > 10:
        return False
    if re.fullmatch(r"\d+", s):  # 纯数字序号不是属性名
        return False
    return any(k in s for k in _ATTR_KEYWORDS)


def _first_col_is_attr(rows) -> bool:
    """第一列（跳过首行）是否主要是属性名短标签"""
    labels = [r[0] for r in rows[1:] if len(r) > 0 and r[0]]
    if not labels:
        return False
    return sum(_looks_like_attr_label(x) for x in labels) / len(labels) >= 0.6


def _first_row_is_attr(row) -> bool:
    """首行是否像属性名表头"""
    cells = [c for c in row if c]
    if not cells:
        return False
    return sum(_looks_like_attr_label(c) for c in cells) / len(cells) >= 0.5


def _row_wise_rows(cleaned) -> List[str]:
    """模式B：表头在第一行，每个数据行生成一条 "表头: 值" 记录"""
    header = cleaned[0]
    result = []
    for row in cleaned[1:]:
        parts = []
        for i, cell in enumerate(row):
            h = header[i] if i < len(header) else ""
            if cell and h:
                parts.append(f"{h}: {cell}")
            elif cell:
                parts.append(cell)
        line = "；".join(parts)
        if line:
            result.append(line)
    return result


def _transpose_rows(cleaned) -> List[str]:
    """模式A：属性名在第一列，按列转置，每一列（除第一列）生成一条记录"""
    ncols = max(len(r) for r in cleaned)
    labels = [r[0] if len(r) > 0 else "" for r in cleaned]
    result = []
    for j in range(1, ncols):
        parts = []
        for i, row in enumerate(cleaned):
            label = labels[i]
            cell = row[j] if j < len(row) else ""
            if cell and label:
                parts.append(f"{label}: {cell}")
            elif cell:
                parts.append(cell)
        line = "；".join(parts)
        if line:
            result.append(line)
    return result


def _table_to_text_rows(rows: List[List]) -> List[str]:
    """把表格二维数组转成可读的文本行列表。

    两种形态：
    - 模式A（横向属性表）：属性名在第一列、实例在不同列 → 按列转置成记录
    - 模式B（纵向记录表）：表头在第一行、每行一条记录 → 每行拼成 "表头: 值"
    两种模式都会先清洗单元格（合并换行），避免竖排文字被切成单字碎片。
    """
    if not rows:
        return []

    # 清洗单元格：转字符串、合并换行、压缩空白、None 视为空
    cleaned = []
    for row in rows:
        cells = [_clean_cell(c) for c in row]
        if any(cells):
            cleaned.append(cells)
    if not cleaned:
        return []

    # 单行表格：无表头，直接拼接非空单元格
    if len(cleaned) == 1:
        return ["；".join(c for c in cleaned[0] if c)]

    # 形态判断：属性名在第一列（横向）→ 模式A；否则模式B
    ncols = max(len(r) for r in cleaned)
    if (2 <= ncols <= 12
            and _first_col_is_attr(cleaned)
            and not _first_row_is_attr(cleaned[0])):
        return _transpose_rows(cleaned)
    return _row_wise_rows(cleaned)


# ============================================================
# PDF
# ============================================================
def load_pdf(path) -> ParsedDocument:
    import pdfplumber

    p = Path(path)
    if not p.exists():
        raise DocumentLoadError(f"文件不存在: {p.name}")

    paragraphs = []
    pages = 0
    idx = 0
    try:
        with pdfplumber.open(str(p)) as pdf:
            pages = len(pdf.pages)
            for page in pdf.pages:
                # 1) 提取正文文本
                text = page.extract_text() or ""
                for line in text.split("\n"):
                    line = line.strip()
                    if line:
                        paragraphs.append({"index": idx, "text": line, "content_type": "text"})
                        idx += 1
                # 2) 提取表格（表格文字 extract_text 不会带出，需单独提取）
                tables = page.extract_tables() or []
                for table in tables:
                    for line in _table_to_text_rows(table):
                        paragraphs.append({"index": idx, "text": line, "content_type": "table"})
                        idx += 1
    except DocumentLoadError:
        raise
    except Exception as e:
        raise DocumentLoadError(f"PDF 解析失败: {p.name} ({e})") from e

    if not paragraphs:
        raise DocumentLoadError(f"PDF 无文字层(疑似扫描件)，未提取到文本: {p.name}")

    return ParsedDocument(path=str(p), file_type="pdf", paragraphs=paragraphs, pages=pages)


# ============================================================
# DOCX
# ============================================================
def load_docx(path) -> ParsedDocument:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    p = Path(path)
    if not p.exists():
        raise DocumentLoadError(f"文件不存在: {p.name}")

    paragraphs = []
    idx = 0
    try:
        doc = docx.Document(str(p))
        W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        # 遍历 body 直接子元素，保持段落与表格的交错顺序
        for child in doc.element.body.iterchildren():
            if child.tag == W + "p":
                text = Paragraph(child, doc).text.strip()
                if text:
                    paragraphs.append({"index": idx, "text": text, "content_type": "text"})
                    idx += 1
            elif child.tag == W + "tbl":
                table = Table(child, doc)
                rows = [[cell.text for cell in row.cells] for row in table.rows]
                for line in _table_to_text_rows(rows):
                    paragraphs.append({"index": idx, "text": line, "content_type": "table"})
                    idx += 1
    except DocumentLoadError:
        raise
    except Exception as e:
        raise DocumentLoadError(f"DOCX 解析失败: {p.name} ({e})") from e

    if not paragraphs:
        raise DocumentLoadError(f"DOCX 未提取到文本: {p.name}")

    return ParsedDocument(path=str(p), file_type="docx", paragraphs=paragraphs)


# ============================================================
# HTML
# ============================================================
def load_html(path) -> ParsedDocument:
    from bs4 import BeautifulSoup

    p = Path(path)
    if not p.exists():
        raise DocumentLoadError(f"文件不存在: {p.name}")

    try:
        raw = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raw = p.read_text(encoding="gbk", errors="ignore")

    paragraphs = []
    try:
        soup = BeautifulSoup(raw, "html.parser")
        # 去掉脚本与样式
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        # 去掉导航栏 / 页脚 / 头部等噪声
        for selector in ["nav", "footer", "header", ".nav", ".footer",
                         ".header", ".menu", ".sidebar", ".breadcrumb", ".copyright"]:
            for el in soup.select(selector):
                el.decompose()

        text = soup.get_text("\n")
        idx = 0
        for line in text.split("\n"):
            line = line.strip()
            if line:
                paragraphs.append({"index": idx, "text": line, "content_type": "text"})
                idx += 1
    except DocumentLoadError:
        raise
    except Exception as e:
        raise DocumentLoadError(f"HTML 解析失败: {p.name} ({e})") from e

    if not paragraphs:
        raise DocumentLoadError(f"HTML 未提取到文本: {p.name}")

    return ParsedDocument(path=str(p), file_type="html", paragraphs=paragraphs)


# ============================================================
# TXT
# ============================================================
def load_txt(path) -> ParsedDocument:
    p = Path(path)
    if not p.exists():
        raise DocumentLoadError(f"文件不存在: {p.name}")

    text = None
    for encoding in ("utf-8", "gbk", "utf-8-sig"):
        try:
            text = p.read_text(encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = p.read_text(encoding="utf-8", errors="ignore")

    paragraphs = []
    idx = 0
    for line in text.split("\n"):
        line = line.strip()
        if line:
            paragraphs.append({"index": idx, "text": line, "content_type": "text"})
            idx += 1

    if not paragraphs:
        raise DocumentLoadError(f"TXT 内容为空: {p.name}")

    return ParsedDocument(path=str(p), file_type="txt", paragraphs=paragraphs)


# ============================================================
# 分发
# ============================================================
_LOADERS = {
    ".pdf": load_pdf,
    ".docx": load_docx,
    ".html": load_html,
    ".htm": load_html,
    ".txt": load_txt,
}


@utils.timed("load_any")
def load_any(path) -> ParsedDocument:
    """按扩展名分发到对应加载器"""
    p = Path(path)
    ext = p.suffix.lower()
    loader = _LOADERS.get(ext)
    if loader is None:
        raise DocumentLoadError(f"不支持的文件类型 {ext!r}: {p.name}")
    return loader(str(p))
