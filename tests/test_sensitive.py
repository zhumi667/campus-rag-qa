"""敏感信息扫描模块的单元测试（src/sensitive.py）

★ 本文件中的手机号、身份证号均为【虚构测试数据】，不要替换为真实号码。


这些测试【不依赖模型、不依赖索引】，可以直接 `pytest` 运行。
"""
from src import sensitive


class TestBlockRules:
    """高风险规则：命中即应阻止入库"""

    def test_id_card_18(self):
        res = sensitive.scan_text("身份证号 110101199001011234 请核对")
        assert any(h.rule == "身份证号" and h.level == "block" for h in res.hits)

    def test_id_card_15(self):
        res = sensitive.scan_text("旧证件 450322199001011")
        assert any(h.level == "block" for h in res.hits)

    def test_mobile(self):
        res = sensitive.scan_text("联系电话 13800138000")
        assert any(h.rule == "手机号" and h.level == "block" for h in res.hits)

    def test_plain_text_has_no_hits(self):
        res = sensitive.scan_text("依据规定，考试不及格者可以参加补考。")
        assert res.hits == []


class TestWarnRules:
    """中风险规则：命中应提示复核，但不阻止入库"""

    def test_email_is_warn_level(self):
        res = sensitive.scan_text("请发送至 teacher@example.com")
        assert any(h.rule == "电子邮箱" and h.level == "warn" for h in res.hits)

    def test_landline_is_warn_level(self):
        res = sensitive.scan_text("办公电话 0773-2290000")
        assert any(h.level == "warn" for h in res.hits)


class TestScanResult:
    def test_text_len_recorded(self):
        text = "短文本"
        res = sensitive.scan_text(text)
        assert res.text_len == len(text)

    def test_hit_carries_context_and_position(self):
        text = "前文" * 10 + "手机 13800138000" + "后文" * 10
        res = sensitive.scan_text(text)
        assert len(res.hits) == 1
        hit = res.hits[0]
        # 上下文应包含敏感值附近的内容，position 应指向命中位置
        assert hit.value in text
        assert isinstance(hit.position, int)
        assert 0 <= hit.position < len(text)

    def test_format_report_returns_text(self):
        res = sensitive.scan_text("手机 13800138000")
        report = sensitive.format_report(res)
        assert isinstance(report, str)
        assert report.strip() != ""
