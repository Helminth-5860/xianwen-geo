from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from django.utils import timezone

from apps.articles.models import Article
from apps.publishing.authorization import _safe_remote_label
from apps.publishing.capabilities import (
    WorkerCapabilitySnapshot,
    clear_worker_capability_cache,
    worker_capability_snapshot,
)
from apps.publishing.catalog import PLATFORMS, platform_payload
from apps.publishing.models import PlatformAccount, Publication, PublicationTarget
from apps.publishing.pause_control import AUTOMATION_PAUSED_CODE, PLATFORM_DISABLED_CODE
from apps.publishing.platform_health import (
    platform_circuit_open,
    record_platform_failure,
    record_platform_success,
)
from apps.publishing.review import AWAITING_REVIEW_CODE
from apps.publishing.runtime_config import validate_runtime_configuration
from apps.publishing.scheduling import _fit_window, _fixed_slot
from apps.publishing.services import (
    PublishingInputError,
    _smart_platform_selection,
    create_publication,
    public_ready_platform_keys,
)
from apps.publishing.target_execution import _target_max_retries
from apps.publishing.tasks import _running_stale_seconds
from apps.publishing.wechat_component import (
    WechatComponentUnavailable,
    _callback_state,
    _session_id_from_callback_state,
)
from apps.publishing.worker_client import PublishingWorkerError, _uncertain_publish_result
from apps.subjects.models import Subject, SubjectType, SubjectVersion
from apps.users.models import User

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


def test_fixed_daily_slots_spread_articles_and_leave_platform_wave_room():
    day = date(2026, 8, 28)
    first = _fixed_slot(day, 0, posts_per_day=2, platform_count=4)
    second = _fixed_slot(day, 1, posts_per_day=2, platform_count=4)
    assert first is not None and second is not None
    assert timezone.localtime(first).time().isoformat(timespec="minutes") == "09:30"
    assert second > first
    # Four platforms need 105 minutes after the article start, so the second slot
    # must be early enough for the complete wave to finish by 20:30.
    assert timezone.localtime(second).time().isoformat(timespec="minutes") == "18:45"


def test_single_daily_article_uses_one_slot_only():
    slot = _fixed_slot(date(2026, 8, 28), 0, posts_per_day=1, platform_count=8)
    assert slot is not None
    assert timezone.localtime(slot).time().isoformat(timespec="minutes") == "09:30"


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
    assert payload["wechat"]["verification_state"] == "unavailable"
    assert payload["wechat"]["supports_public_publish"] is False


def test_wechat_callback_state_is_signed_and_bound_to_the_session():
    session_id = "11111111-2222-4333-8444-555555555555"
    state = _callback_state(session_id)
    assert session_id not in state
    assert str(_session_id_from_callback_state(state)) == session_id

    with pytest.raises(WechatComponentUnavailable):
        _session_id_from_callback_state(f"{state}tampered")


def test_environment_allowlist_cannot_claim_unverified_worker_capabilities():
    payload = {
        item["key"]: item
        for item in platform_payload(
            {"zhihu"},
            worker_available=True,
        )
    }
    assert payload["zhihu"]["authorization_enabled"] is False
    assert payload["zhihu"]["supports_draft"] is False
    assert payload["zhihu"]["supports_public_publish"] is False
    assert payload["zhihu"]["can_enable_auto"] is False


def test_verified_capabilities_are_exposed_separately():
    payload = {
        item["key"]: item
        for item in platform_payload(
            {"zhihu"},
            worker_capabilities={
                "zhihu": frozenset({"auth", "draft", "public_publish"}),
            },
            worker_available=True,
        )
    }
    assert payload["zhihu"]["authorization_verified"] is True
    assert payload["zhihu"]["supports_draft"] is True
    assert payload["zhihu"]["supports_public_publish"] is True
    assert payload["zhihu"]["can_enable_auto"] is True
    assert payload["zhihu"]["image_upload_verified"] is False
    assert payload["zhihu"]["availability_stage"] == "public_ready"


def test_internal_validation_can_use_implemented_auth_without_claiming_public_publish():
    payload = {
        item["key"]: item
        for item in platform_payload(
            implemented_capabilities={
                "zhihu": frozenset({"auth", "draft", "public_publish"}),
            },
            validation_keys={"zhihu"},
            worker_available=True,
            internal_validation=True,
        )
    }
    assert payload["zhihu"]["authorization_enabled"] is True
    assert payload["zhihu"]["authorization_validation_available"] is True
    assert payload["zhihu"]["draft_validation_available"] is True
    assert payload["zhihu"]["supports_public_publish"] is False
    assert payload["zhihu"]["can_enable_auto"] is False
    assert payload["zhihu"]["availability_stage"] == "draft_validation"


def test_internal_validation_gate_is_invisible_to_ordinary_users():
    payload = {
        item["key"]: item
        for item in platform_payload(
            implemented_capabilities={"zhihu": frozenset({"auth", "draft"})},
            validation_keys={"zhihu"},
            worker_available=True,
            internal_validation=False,
        )
    }
    assert payload["zhihu"]["authorization_enabled"] is False
    assert payload["zhihu"]["authorization_validation_available"] is False
    assert payload["zhihu"]["supports_draft"] is False


def test_worker_capability_snapshot_keeps_implemented_and_verified_separate(monkeypatch):
    clear_worker_capability_cache()
    monkeypatch.setattr(
        "apps.publishing.capabilities.publishing_capabilities",
        lambda: {
            "publishers": [
                {
                    "platform_key": "zhihu",
                    "implemented_capabilities": [
                        "auth",
                        "draft",
                        "public_publish",
                    ],
                    "verified_capabilities": ["auth", "draft"],
                }
            ]
        },
    )
    snapshot = worker_capability_snapshot(force_refresh=True)
    assert snapshot.service_available is True
    assert snapshot.verified_for("zhihu") == frozenset({"auth", "draft"})
    assert snapshot.implemented_for("zhihu") == frozenset(
        {"auth", "draft", "public_publish"}
    )
    clear_worker_capability_cache()


def test_legacy_worker_capabilities_are_internal_validation_only(monkeypatch):
    clear_worker_capability_cache()
    monkeypatch.setattr(
        "apps.publishing.capabilities.publishing_capabilities",
        lambda: {
            "publishers": [
                {
                    "platform_key": "zhihu",
                    "verified_capabilities": ["auth", "draft"],
                }
            ]
        },
    )
    snapshot = worker_capability_snapshot(force_refresh=True)
    assert snapshot.verified_for("zhihu") == frozenset()
    assert snapshot.implemented_for("zhihu") == frozenset({"auth", "draft"})
    clear_worker_capability_cache()


def test_worker_capability_failure_is_fail_closed(monkeypatch):
    clear_worker_capability_cache()

    def unavailable():
        raise PublishingWorkerError("worker_unavailable")

    monkeypatch.setattr(
        "apps.publishing.capabilities.publishing_capabilities",
        unavailable,
    )
    snapshot = worker_capability_snapshot(force_refresh=True)
    assert snapshot.service_available is False
    assert snapshot.verified_platforms == {}
    assert snapshot.implemented_platforms == {}
    clear_worker_capability_cache()


def test_public_ready_platforms_require_both_rollout_and_verified_public_capability(
    monkeypatch,
):
    monkeypatch.delenv("PUBLISHING_VALIDATION_PLATFORM_KEYS", raising=False)
    implemented_only = WorkerCapabilitySnapshot(
        service_available=True,
        verified_platforms={},
        implemented_platforms={
            "zhihu": frozenset({"auth", "draft", "public_publish"}),
        },
    )
    verified = WorkerCapabilitySnapshot(
        service_available=True,
        verified_platforms={
            "zhihu": frozenset({"auth", "draft", "public_publish"}),
        },
        implemented_platforms={
            "zhihu": frozenset({"auth", "draft", "public_publish"}),
        },
    )
    with override_settings(PUBLISHING_ENABLED_PLATFORM_KEYS=("zhihu",)):
        assert public_ready_platform_keys(snapshot=implemented_only) == set()
        assert public_ready_platform_keys(snapshot=verified) == {"zhihu"}


def test_worker_account_labels_are_bounded_and_control_characters_are_removed():
    assert _safe_remote_label("  企业\n账号\x00  ") == "企业 账号"
    assert len(_safe_remote_label("用" * 300)) == 255
    assert _safe_remote_label({"unexpected": "value"}) == ""


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


def test_production_enabled_platforms_require_dedicated_encryption_key(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PUBLISHING_WORKER_EXPERIMENTAL_PLATFORM_KEYS", "zhihu")
    with override_settings(
        PUBLISHING_ENABLED_PLATFORM_KEYS=("zhihu",),
        PUBLISHING_WORKER_BASE_URL="http://publishing-worker:8092",
        PUBLISHING_WORKER_INTERNAL_SECRET="x" * 32,
        PUBLISHING_CREDENTIAL_ENCRYPTION_KEY="",
    ):
        with pytest.raises(ImproperlyConfigured):
            validate_runtime_configuration()


def test_browser_platform_gate_must_match_worker_gate(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PUBLISHING_WORKER_EXPERIMENTAL_PLATFORM_KEYS", "")
    with override_settings(
        PUBLISHING_ENABLED_PLATFORM_KEYS=("zhihu",),
        PUBLISHING_WORKER_BASE_URL="http://publishing-worker:8092",
        PUBLISHING_WORKER_INTERNAL_SECRET="x" * 32,
        PUBLISHING_CREDENTIAL_ENCRYPTION_KEY=Fernet.generate_key().decode("ascii"),
    ):
        with pytest.raises(ImproperlyConfigured):
            validate_runtime_configuration()


def test_valid_dedicated_key_allows_enabled_platform_runtime(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PUBLISHING_WORKER_EXPERIMENTAL_PLATFORM_KEYS", "zhihu")
    with override_settings(
        PUBLISHING_ENABLED_PLATFORM_KEYS=("zhihu",),
        PUBLISHING_WORKER_BASE_URL="http://publishing-worker:8092",
        PUBLISHING_WORKER_INTERNAL_SECRET="x" * 32,
        PUBLISHING_CREDENTIAL_ENCRYPTION_KEY=Fernet.generate_key().decode("ascii"),
    ):
        validate_runtime_configuration()


def test_unknown_validation_platform_is_rejected(monkeypatch):
    monkeypatch.setenv("PUBLISHING_VALIDATION_PLATFORM_KEYS", "unknown-platform")
    with override_settings(PUBLISHING_ENABLED_PLATFORM_KEYS=()):
        with pytest.raises(ImproperlyConfigured):
            validate_runtime_configuration()


def test_internal_validation_requires_production_credential_encryption(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PUBLISHING_VALIDATION_PLATFORM_KEYS", "zhihu")
    with override_settings(
        PUBLISHING_ENABLED_PLATFORM_KEYS=(),
        PUBLISHING_WORKER_BASE_URL="http://publishing-worker:8092",
        PUBLISHING_WORKER_INTERNAL_SECRET="x" * 32,
        PUBLISHING_CREDENTIAL_ENCRYPTION_KEY="",
    ):
        with pytest.raises(ImproperlyConfigured):
            validate_runtime_configuration()


def test_internal_validation_requires_matching_worker_gate(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PUBLISHING_VALIDATION_PLATFORM_KEYS", "zhihu")
    monkeypatch.setenv("PUBLISHING_WORKER_EXPERIMENTAL_PLATFORM_KEYS", "")
    with override_settings(
        PUBLISHING_ENABLED_PLATFORM_KEYS=(),
        PUBLISHING_WORKER_BASE_URL="http://publishing-worker:8092",
        PUBLISHING_WORKER_INTERNAL_SECRET="x" * 32,
        PUBLISHING_CREDENTIAL_ENCRYPTION_KEY=Fernet.generate_key().decode("ascii"),
    ):
        with pytest.raises(ImproperlyConfigured):
            validate_runtime_configuration()


def test_internal_validation_accepts_matching_worker_gate(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PUBLISHING_VALIDATION_PLATFORM_KEYS", "zhihu")
    monkeypatch.setenv("PUBLISHING_WORKER_EXPERIMENTAL_PLATFORM_KEYS", "zhihu")
    with override_settings(
        PUBLISHING_ENABLED_PLATFORM_KEYS=(),
        PUBLISHING_WORKER_BASE_URL="http://publishing-worker:8092",
        PUBLISHING_WORKER_INTERNAL_SECRET="x" * 32,
        PUBLISHING_CREDENTIAL_ENCRYPTION_KEY=Fernet.generate_key().decode("ascii"),
    ):
        validate_runtime_configuration()


@pytest.mark.django_db
def test_same_article_cannot_be_arranged_twice_for_the_same_live_platform(monkeypatch):
    user = User.objects.create_user(
        phone="13900000001",
        nickname="重复发布保护测试",
        password="test-password",
    )
    subject_type = SubjectType.objects.create(key="publishing-test", name="发布测试")
    subject = Subject.objects.create(
        user=user,
        subject_type=subject_type,
        status=Subject.Status.ACTIVE,
        schema_version=1,
        schema_snapshot={},
        schema_digest="schema-digest",
    )
    subject_version = SubjectVersion.objects.create(
        subject=subject,
        version_no=1,
        field_values={},
        schema_version=1,
        schema_snapshot={},
        schema_digest="schema-digest",
        field_values_digest="field-values-digest",
        semantic_digest="semantic-digest",
        official_name="发布测试主体",
        created_by=user,
    )
    subject.current_version = subject_version
    subject.save(update_fields=("current_version", "updated_at"))
    article = Article.objects.create(
        user=user,
        subject=subject,
        subject_version=subject_version,
        custom_type="测试文章",
        title="同一篇文章不能重复安排",
        content="这是用于验证重复发文保护的完整正文。",
        status=Article.Status.READY,
    )
    PlatformAccount.objects.create(
        user=user,
        subject=subject,
        platform_key="zhihu",
        auth_method=PlatformAccount.AuthMethod.BROWSER_SESSION,
        status=PlatformAccount.Status.CONNECTED,
        enabled_for_auto=True,
    )
    monkeypatch.setattr(
        "apps.publishing.services.public_ready_platform_keys",
        lambda: {"zhihu"},
    )

    with pytest.raises(PublishingInputError, match="通过内容检查"):
        create_publication(
            user=user,
            subject_id=subject.id,
            article_id=article.id,
            platform_keys=["zhihu"],
        )

    article.moderation_status = Article.Moderation.PASSED
    article.save(update_fields=("moderation_status", "updated_at"))

    first = create_publication(
        user=user,
        subject_id=subject.id,
        article_id=article.id,
        platform_keys=["zhihu"],
    )
    assert first.targets.count() == 1

    with pytest.raises(PublishingInputError, match="请勿重复提交"):
        create_publication(
            user=user,
            subject_id=subject.id,
            article_id=article.id,
            platform_keys=["zhihu"],
        )

    assert Publication.objects.filter(article=article).count() == 1


def test_late_platform_wave_rolls_to_next_day():
    tz = timezone.get_current_timezone()
    late = timezone.make_aware(datetime(2026, 8, 28, 20, 0), timezone=tz)
    fitted = _fit_window(late, platform_count=4)
    local = timezone.localtime(fitted)
    assert local.date().isoformat() == "2026-08-29"
    assert (local.hour, local.minute) == (9, 30)
