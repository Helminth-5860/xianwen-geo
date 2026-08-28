from __future__ import annotations

from datetime import datetime

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.publishing.catalog import PLATFORMS, platform_payload
from apps.publishing.models import PublicationTarget
from apps.publishing.platform_health import (
    platform_circuit_open,
    record_platform_failure,
    record_platform_success,
)
from apps.publishing.review import AWAITING_REVIEW_CODE
from apps.publishing.scheduling import _fit_window
from apps.publishing.target_execution import _target_max_retries
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


def test_publication_target_has_explicit_platform_review_state():
    values = {value for value, _label in PublicationTarget.Status.choices}
    assert "submitted" in values
    assert "submitted" != PublicationTarget.Status.SUCCEEDED


def test_review_gate_uses_distinct_non_publishable_reason():
    assert AWAITING_REVIEW_CODE == "awaiting_review"
    assert AWAITING_REVIEW_CODE not in {"authorization_required", "platform_unavailable"}


@pytest.mark.django_db
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


def test_late_platform_wave_rolls_to_next_day():
    tz = timezone.get_current_timezone()
    late = timezone.make_aware(datetime(2026, 8, 28, 20, 0), timezone=tz)
    fitted = _fit_window(late, platform_count=4)
    local = timezone.localtime(fitted)
    assert local.date().isoformat() == "2026-08-29"
    assert (local.hour, local.minute) == (9, 30)
