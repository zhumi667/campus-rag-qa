"""文档状态与生效日期过滤的单元测试（src/retriever.py）

★ 测试技巧：用 Retriever.__new__(Retriever) 绕过 __init__，
  从而【不加载索引与嵌入模型】也能测纯判断逻辑。
  这让整个测试套件无需 GPU / 模型即可运行。

★ 被保护的规则（对应 config.VERSION_FILTER_ENABLED）：
  ① status 必须是 active（inactive=已失效 / draft=草稿 都不应被引用）
  ② effective_date 若存在，必须 <= 基准日期（尚未生效的不能引用）
  ③ expire_date   若存在，必须 >  基准日期（已过期的不能引用）
"""
import datetime

import pytest

import config
from src.retriever import Retriever


@pytest.fixture()
def retriever():
    """不初始化索引/模型的 Retriever 实例（只用于测纯逻辑）"""
    return Retriever.__new__(Retriever)


class TestStatusFilter:
    def test_active_is_retrievable(self, retriever):
        assert retriever._is_retrievable({"status": "active"}) is True

    def test_inactive_is_blocked(self, retriever):
        assert retriever._is_retrievable({"status": "inactive"}) is False

    def test_draft_is_blocked(self, retriever):
        assert retriever._is_retrievable({"status": "draft"}) is False

    def test_missing_status_defaults_to_active(self, retriever):
        assert retriever._is_retrievable({}) is True


class TestEffectiveDate:
    def test_future_effective_date_is_blocked(self, retriever):
        assert retriever._is_retrievable(
            {"status": "active", "effective_date": "2099-01-01"}
        ) is False

    def test_past_effective_date_is_allowed(self, retriever):
        assert retriever._is_retrievable(
            {"status": "active", "effective_date": "2020-01-01"}
        ) is True

    def test_empty_effective_date_is_allowed(self, retriever):
        assert retriever._is_retrievable(
            {"status": "active", "effective_date": ""}
        ) is True


class TestExpireDate:
    def test_expired_document_is_blocked(self, retriever):
        assert retriever._is_retrievable(
            {"status": "active", "expire_date": "2000-01-01"}
        ) is False

    def test_future_expire_date_is_allowed(self, retriever):
        assert retriever._is_retrievable(
            {"status": "active", "expire_date": "2099-12-31"}
        ) is True


class TestAsOfDateOverride:
    """基准日期可切换：同一份文档在不同时点可见性不同"""

    def test_visible_inside_validity_window(self, retriever, monkeypatch):
        monkeypatch.setattr(config, "DEFAULT_AS_OF_DATE", "2026-03-01")
        meta = {"status": "active",
                "effective_date": "2026-01-01",
                "expire_date": "2026-06-30"}
        assert retriever._is_retrievable(meta) is True

    def test_invisible_after_validity_window(self, retriever, monkeypatch):
        monkeypatch.setattr(config, "DEFAULT_AS_OF_DATE", "2026-12-01")
        meta = {"status": "active",
                "effective_date": "2026-01-01",
                "expire_date": "2026-06-30"}
        assert retriever._is_retrievable(meta) is False


class TestFilterDisabled:
    """开关关闭时必须回到旧行为（不过滤任何文档）"""

    def test_disabled_allows_everything(self, retriever, monkeypatch):
        monkeypatch.setattr(config, "VERSION_FILTER_ENABLED", False)
        assert retriever._is_retrievable({"status": "inactive"}) is True
        assert retriever._is_retrievable(
            {"status": "active", "effective_date": "2099-01-01"}
        ) is True
        assert retriever._is_retrievable(
            {"status": "active", "expire_date": "2000-01-01"}
        ) is True


class TestOverfetch:
    """状态过滤开启时会超取候选，避免滤完不足 top_k"""

    def test_overfetch_multiplies(self, retriever, monkeypatch):
        monkeypatch.setattr(config, "VERSION_FILTER_ENABLED", True)
        monkeypatch.setattr(config, "RETRIEVE_OVERFETCH", 3)
        assert retriever._fetch_k(5) == 15

    def test_overfetch_capped_at_200(self, retriever, monkeypatch):
        monkeypatch.setattr(config, "VERSION_FILTER_ENABLED", True)
        monkeypatch.setattr(config, "RETRIEVE_OVERFETCH", 3)
        assert retriever._fetch_k(1000) == 200

    def test_no_overfetch_when_disabled(self, retriever, monkeypatch):
        monkeypatch.setattr(config, "VERSION_FILTER_ENABLED", False)
        assert retriever._fetch_k(5) == 5


class TestDefaultAsOfDate:
    """DEFAULT_AS_OF_DATE 为空时应回退到当天"""

    def test_none_falls_back_to_today(self, retriever, monkeypatch):
        monkeypatch.setattr(config, "DEFAULT_AS_OF_DATE", None)
        # 今天之前生效的文档应可见
        past = (datetime.date.today() - datetime.timedelta(days=365)).isoformat()
        assert retriever._is_retrievable(
            {"status": "active", "effective_date": past}
        ) is True
        # 明天才生效的文档应不可见
        future = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        assert retriever._is_retrievable(
            {"status": "active", "effective_date": future}
        ) is False
