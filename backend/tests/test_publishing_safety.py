from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from django.core.cache import cache
from django.utils import timezone

from apps.publishing.catalog import PLATFORMS, platform_payload
from apps.publishing.models import Publication, PublicationTarget
from apps.publishing.pause_control import AUTOMATION_PAUSED_CODE, PLATFORM_DISABLED_CODE
from apps.publishing.platform_health import (
    platform_circuit_open,
    record_platform_failure,
    record_platform_success,
)
from apps.publishing.review import AWAITING_REVIEW_CODE
from apps.publishing.scheduling import _fit_window
from apps.publishing.services import _smart_platform_selection
from apps.publishing.target_execution import _target_max_retries
from apps.publishing.tasks import _running_stale_seconds
from apps.publishing.worker_client import _uncertain_publish_result


EXPECTED_PLATFORM_KEYS = {
    "wechat",
    "toutiao",
    "baijiahao",
    "zhihu",
    "xiaohongshu",
    "weibo",
    "bilibili",
    "douyin",
    "qq",
    "sohu",
    "csdn",
    "juejin",
    "cnblogs",
    "oschina",
    "segmentfault",
    "jianshu",
    "douban",
}


def test_domestic_platform_catalog_is_exactly_seventeen():
    keys = {item.key for item in PLATFORMS}
    assert keys == EXPECTED_PLATFORM_KEYS
    assert len(PLATFORMS) == 17


def test_publication_and_target_have_explicit_non_success_states():
    publication_values = {value for value, _label in Publication.Status.choices}
    target_values = {value for value, _label in PublicationTarget.Status.choices}
    assert Publication.Status.PAUSED in publication_values
    assert "submitted" in target_values
    assert "submitted" != PublicationTarget.Status.SUCCEEDED


def test_review_and_pause_reasons_are_distinct():
    assert AWAITING_REVIEW_CODE == "awaiting_review"
    assert AUTOMATION_PAUSED_CODE == "automation_paused"
    assert PLATFORM_DISABLED_CODE == "platform_disabled"
    assert len({AWAITING_REVIEW_CODE, AUTOMATION_PAUSED_CODE, PLATFORM_DISABLED_CODE}) == 3
    assert not {
        AWAITING_REVIEW_CODE,
        AUTOMATION_PAUSED_CODE,
        PLATFORM_DISABLED_CODE,
    } & {"authorization_required", "platform_unavailable"}


def test_smart_distribution_prioritizes_technical_channels_and_is_bounded():
    article = SimpleNamespace(
        title="API 与数据库架构实践",
        content="本文介绍系统架构、接口、数据库和部署方法。",
        template_version=None,
        article_type_id=None,
        article_type=None,
    )
    selected = _smart_platform_selection(article, EXPECTED_PLATFORM_KEYS)
    assert selected[0] == "csdn"
    assert selected[1] == "juejin"
    assert "segmentfault" in selected
    assert len(selected) <= 8
    assert set(selected) < EXPECTED_PLATFORM_KEYS


def test_smart_distribution_prioritizes_visual_channels_for_product_guides():
    article = SimpleNamespace(
        title="企业产品选择指南与使用场景",
        content="用清单和步骤说明产品怎么选，并展示不同使用场景。",
        template_version=None,
        article_type_id=None,
        article_type=None,
    )
    selected = _smart_platform_selection(article, EXPECTED_PLATFORM_KEYS)
    assert selected[0] == "xiaohongshu"
    assert "douyin" in selected
    assert "bilibili" in selected
    assert len(selected) <= 8


def test_wechat_is_not_exposed_without_component_ticket(monkeypatch):
    cache.clear()
    monkeypatch.setenv("PUBLISHING_WECHAT_COMPONENT_APP_ID", "wx-component-test")
    monkeypatch.setenv("PUBLISHING_WECHAT_COMPONENT_APP_SECRET", "test-secret")
    monkeypatch.setenv("PUBLISHING_WECHAT_COMPONENT_TOKEN", "test-token")
    monkeypatch.setenv("PUBLISHING_WECHAT_COMPONENT_AES_KEY", "A" * 43)
    monkeypatch.setenv(
        "PUBLISHING_WECHAT_COMPONENT_REDIRECT_URL",
        "https://example.test/api/v1/publishing/wechat/component/callback",
    )

    payload = {item["key"]: item for item in platform_payload({"wechat"})}
    assert payload["wechat"]["authorization_enabled"] is False
    assert payload["wechat"]["verification_state"] == "validation"


def test_platform_circuit_breaker_opens_and_success_resets():
    cache.clear()
    for _ in range(5):
        record_platform_failure("test-platform", "editor_changed")
    assert platform_circuit_open("test-platform") is True

    record_platform_success("test-platform")
    assert platform_circuit_open("test-platform") is False


def test_uncertain_publish_result_is_not_retry_success():
    cache.clear()
    result = _uncertain_publish_result("test-platform")
    assert result["success"] is False
    assert result["status"] == "action_required"
    assert result["safeErrorCode"] == "publish_result_unconfirmed"


def test_retry_count_is_bounded_from_environment(monkeypatch):
    monkeypatch.setenv("PUBLISHING_TARGET_MAX_RETRIES", "999")
    assert _target_max_retries() == 10
    monkeypatch.setenv("PUBLISHING_TARGET_MAX_RETRIES", "not-a-number")
    assert _target_max_retries() == 3


def test_running_stale_window_is_always_beyond_publish_task_limit(monkeypatch):
    monkeypatch.setenv("PUBLISHING_RUNNING_STALE_SECONDS", "1")
    assert _running_stale_seconds() >= 390
    monkeypatch.setenv("PUBLISHING_RUNNING_STALE_SECONDS", "99999")
    assert _running_stale_seconds() == 3600


def test_late_platform_wave_rolls_to_next_day():
    tz = timezone.get_current_timezone()
    late = timezone.make_aware(datetime(2026, 8, 28, 20, 0), timezone=tz)
    fitted = _fit_window(late, platform_count=4)
    local = timezone.localtime(fitted)
    assert local.date().isoformat() == "2026-08-29"
    assert (local.hour, local.minute) == (9, 30)
