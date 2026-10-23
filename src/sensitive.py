"""src/sensitive.py — 敏感信息扫描

★ 设计原则：两档风险 + 严格规则，避免误报拦下正常语料。
  · 高风险（block）：一旦命中必须人工确认才能入库（身份证、手机号、银行卡、学号）
  · 中风险（warn） ：提示管理员复核（邮箱、座机、联系人姓名）

★ 为什么不用"QQ号"这类宽泛规则：
  实测发现 `\b[1-9]\d{4,10}\b` 在培养方案中命中 85 处，全部是【课程代码】
  （如 220019 人工智能数学基础）。过宽的规则会让正常语料无法入库，
  因此本模块只保留有明确语义锚点的规则。
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------- 规则表
# (风险等级, 规则名, 正则, 说明)
RULES = [
    # ---- 高风险：唯一指向个人 ----
    ("block", "身份证号", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"),
     "18 位身份证号码"),
    ("block", "身份证号(15位)", re.compile(r"(?<!\d)\d{15}(?!\d)"),
     "旧版 15 位身份证号码"),
    ("block", "手机号", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
     "中国大陆手机号"),
    ("block", "银行卡号", re.compile(r"(?<!\d)\d{16,19}(?!\d)"),
     "16–19 位银行卡/账号（可能与表格数字混淆，需人工确认）"),
    ("block", "学号", re.compile(r"(?<![\dA-Za-z])(?:20\d{2})\d{6,10}(?!\d)"),
     "以入学年份开头的学号"),

    # ---- 中风险：可能是公开信息，也可能是个人 ----
    ("warn", "电子邮箱", re.compile(r"[\w.\-+]+@[\w\-]+\.[A-Za-z]{2,}"),
     "邮箱地址"),
    ("warn", "座机电话", re.compile(r"(?<!\d)0\d{2,3}[-\s]?\d{7,8}(?!\d)"),
     "固定电话（多为办公电话）"),
    ("warn", "联系人姓名", re.compile(r"联系人[：:是为\s]{0,3}([\u4e00-\u9fa5]{2,4})(?=[，,、。\s]|$|联系电话)"),
     "出现「联系人：X」形式的姓名"),
    ("warn", "疑似姓名+电话", re.compile(r"([\u4e00-\u9fa5]{2,4})[，,、\s]{0,3}(?:联系)?电话[：:是为\s]{0,3}(?:\d[\d\-\s]{6,})"),
     "姓名与电话相邻出现"),
]

# 白名单：命中的文本片段若包含这些词，视为正常内容（降低误报）
WHITELIST_CONTEXT = [
    "课程代码", "课程名称", "学分数", "咨询电话", "招生", "传真",
    "邮政编码", "邮编", "区号", "举报电话", "监督电话",
]


@dataclass
class Hit:
    level: str          # block / warn
    rule: str           # 规则名
    value: str          # 命中文本
    context: str        # 上下文（前后各 30 字）
    position: int       # 在全文中的位置


@dataclass
class ScanResult:
    hits: list = field(default_factory=list)
    text_len: int = 0

    @property
    def blocks(self) -> list:
        return [h for h in self.hits if h.level == "block"]

    @property
    def warns(self) -> list:
        return [h for h in self.hits if h.level == "warn"]

    @property
    def ok(self) -> bool:
        """无高风险命中即可入库（中风险仅提示）"""
        return not self.blocks

    def summary(self) -> dict:
        return {
            "ok": self.ok,
            "text_len": self.text_len,
            "block_count": len(self.blocks),
            "warn_count": len(self.warns),
            "blocks": [{"rule": h.rule, "value": h.value, "context": h.context}
                       for h in self.blocks[:20]],
            "warns": [{"rule": h.rule, "value": h.value, "context": h.context}
                      for h in self.warns[:20]],
        }


def scan_text(text: str) -> ScanResult:
    """扫描一段文本，返回命中结果。"""
    res = ScanResult(text_len=len(text))
    for level, name, pat, _desc in RULES:
        for m in pat.finditer(text):
            value = m.group(0)
            s = max(0, m.start() - 30)
            e = min(len(text), m.end() + 30)
            ctx = text[s:e].replace("\n", " ")
            # 白名单：上下文含正常词汇则跳过
            if any(w in ctx for w in WHITELIST_CONTEXT):
                continue
            # 银行号规则常与表格数字混淆：单独再过滤
            if name == "银行卡号" and _looks_like_table_number(ctx):
                continue
            res.hits.append(Hit(level=level, rule=name, value=value,
                                context=ctx, position=m.start()))
    return res


def _looks_like_table_number(ctx: str) -> bool:
    """16-19 位连续数字若出现在表格/课程/学分语境，多半是数据而非卡号。"""
    table_markers = ["学分", "学时", "必修", "选修", "课程", "合计", "总计", "小计", "人数"]
    return any(w in ctx for w in table_markers)


def scan_file(path: Path) -> ScanResult:
    """扫描一个文本文件。"""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        r = ScanResult(text_len=0)
        r.hits.append(Hit(level="warn", rule="读取失败", value=str(e)[:60],
                          context="", position=0))
        return r
    return scan_text(text)


def format_report(res: ScanResult) -> str:
    """生成人类可读的扫描报告。"""
    lines = []
    lines.append(f"文本长度: {res.text_len} 字符")
    lines.append(f"高风险命中: {len(res.blocks)} 处")
    lines.append(f"中风险命中: {len(res.warns)} 处")
    if res.blocks:
        lines.append("")
        lines.append("★ 高风险（需人工确认后才可入库）:")
        for h in res.blocks[:20]:
            lines.append(f"    [{h.rule}] {h.value}")
            lines.append(f"        …{h.context}…")
    if res.warns:
        lines.append("")
        lines.append("中风险（请复核是否为公开信息）:")
        for h in res.warns[:20]:
            lines.append(f"    [{h.rule}] {h.value}")
            lines.append(f"        …{h.context}…")
    if not res.hits:
        lines.append("")
        lines.append("✅ 未发现敏感信息")
    return "\n".join(lines)
