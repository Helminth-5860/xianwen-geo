from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.articles.models import Article
from apps.subjects.models import Subject

from .catalog import PLATFORM_BY_KEY, platform_payload
from .models import (
    PlatformAccount,
    PlatformAuthorizationSession,
    Publication,
    PublicationTarget,
    PublishingPreference,
)
from .security import encrypt_secret, issue_one_time_token


class PublishingInputError(ValueError):
    pass


_SMART_BY_ARTICLE_TYPE: dict[str, tuple[str, ...]] = {
    "brand_story": ("wechat", "baijiahao", "toutiao", "sohu", "zhihu", "weibo", "qq"),
    "industry_insight": ("zhihu", "wechat", "baijiahao", "toutiao", "sohu", "qq", "weibo"),
    "product_guide": ("xiaohongshu", "wechat", "baijiahao", "toutiao", "zhihu", "douyin", "bilibili", "weibo"),
    "faq_article": ("zhihu", "baijiahao", "wechat", "toutiao", "sohu"),
}
_SMART_DEFAULT = ("zhihu", "wechat", "baijiahao", "toutiao", "sohu", "qq", "weibo")
_SMART_TECH = ("csdn", "juejin", "cnblogs", "segmentfault", "oschina", "zhihu", "bilibili")
_SMART_VISUAL = ("xiaohongshu", "douyin", "bilibili", "weibo", "toutiao")
_TECH_CUES = ("api", "代码", "开发", "技术", "架构", "算法", "数据库", "模型", "接口", "部署", "系统设计")
_VISUAL_CUES = ("产品", "指南", "体验", "案例", "清单", "步骤", "场景", "对比", "怎么选", "推荐")


def enabled_platform_keys() -> set[str]:
    configured = getattr(settings, "PUBLISHING_ENABLED_PLATFORM_KEYS", ())
    return {str(item).strip() for item in configured if str(item).strip() in PLATFORM_BY_KEY}


def subject_for_user(*, user, subject_id) -> Subject:
    return get_object_or_404(Subject.objects.select_related("current_version"), id=subject_id, user=user)


def preference_for_subject(*, user, subject: Subject) -> PublishingPreference:
    preference, _ = PublishingPreference.objects.get_or_create(
        user=user,
        subject=subject,
        defaults={
            "mode": PublishingPreference.Mode.MANAGED,
            "distribution_strategy": PublishingPreference.DistributionStrategy.SMART,
            "image_strategy": PublishingPreference.ImageStrategy.CUSTOMER_FIRST,
            "image_density": PublishingPreference.ImageDensity.STANDARD,
            "frequency_mode": PublishingPreference.FrequencyMode.SMART,
            "posts_per_day": 1,
        },
    )
    return preference


def preference_payload(preference: PublishingPreference) -> dict[str, Any]:
    return {
        "id": str(preference.id),
        "is_enabled": preference.is_enabled,
        "mode": preference.mode,
        "distribution_strategy": preference.distribution_strategy,
        "custom_platform_keys": list(preference.custom_platform_keys or []),
        "image_strategy": preference.image_strategy,
        "image_density": preference.image_density,
        "frequency_mode": preference.frequency_mode,
        "posts_per_day": preference.posts_per_day,
        "version": preference.version,
        "updated_at": preference.updated_at.isoformat(),
    }


def account_payload(account: PlatformAccount) -> dict[str, Any]:
    definition = PLATFORM_BY_KEY.get(account.platform_key)
    return {
        "id": str(account.id),
        "platform_key": account.platform_key,
        "platform_name": definition.name if definition else account.platform_key,
        "auth_method": account.auth_method,
        "status": account.status,
        "display_name": account.display_name,
        "enabled_for_auto": account.enabled_for_auto,
        "session_expires_at": account.session_expires_at.isoformat() if account.session_expires_at else None,
        "last_checked_at": account.last_checked_at.isoformat() if account.last_checked_at else None,
        "needs_action": account.status in {PlatformAccount.Status.EXPIRED, PlatformAccount.Status.ACTION_REQUIRED},
        "updated_at": account.updated_at.isoformat(),
    }


def auth_session_payload(session: PlatformAuthorizationSession, *, one_time_token: str | None = None) -> dict[str, Any]:
    payload = {
        "id": str(session.id),
        "platform_key": session.platform_key,
        "auth_method": session.auth_method,
        "status": session.status,
        "action_url": session.action_url,
        "expires_at": session.expires_at.isoformat(),
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        "error_message": _safe_auth_error(session.safe_error_code),
    }
    if one_time_token:
        payload["one_time_token"] = one_time_token
    return payload


def _safe_auth_error(code: str) -> str:
    return {
        "authorization_timeout": "授权时间已结束，请重新授权",
        "platform_unavailable": "当前平台暂时无法完成授权，请稍后再试",
        "authorization_cancelled": "本次授权未完成",
    }.get(code, "" if not code else "本次授权未完成，请重新尝试")


def publication_target_payload(target: PublicationTarget) -> dict[str, Any]:
    definition = PLATFORM_BY_KEY.get(target.platform_key)
    return {
        "id": str(target.id),
        "platform_key": target.platform_key,
        "platform_name": definition.name if definition else target.platform_key,
        "status": target.status,
        "scheduled_at": target.scheduled_at.isoformat() if target.scheduled_at else None,
        "submitted_at": target.submitted_at.isoformat() if target.submitted_at else None,
        "published_at": target.published_at.isoformat() if target.published_at else None,
        "management_url": target.management_url,
        "public_url": target.public_url,
        "attempts": target.attempts,
        "error_message": _safe_publish_error(target.safe_error_code),
    }


def publication_payload(publication: Publication) -> dict[str, Any]:
    targets = list(publication.targets.all())
    return {
        "id": str(publication.id),
        "article_id": str(publication.article_id),
        "title": publication.source_title,
        "status": publication.status,
        "awaiting_review": any(
            item.status == PublicationTarget.Status.PAUSED
            and item.safe_error_code == "awaiting_review"
            for item in targets
        ),
        "distribution_strategy": publication.distribution_strategy,
        "image_strategy": publication.image_strategy,
        "scheduled_at": publication.scheduled_at.isoformat() if publication.scheduled_at else None,
        "created_at": publication.created_at.isoformat(),
        "targets": [publication_target_payload(item) for item in targets],
    }


def _safe_publish_error(code: str) -> str:
    return {
        "authorization_required": "账号需要重新授权",
        "platform_unavailable": "当前平台暂不可用，系统会稍后处理",
        "content_rejected": "内容未通过平台发布要求，请检查后重试",
        "media_invalid": "图片不符合平台要求，系统正在重新处理",
        "awaiting_review": "内容和配图已准备好，等待确认发布",
        "automation_paused": "自动发文已暂停，重新开启后会继续",
        "platform_disabled": "该平台已暂停参与自动发文",
        "public_publish_not_verified": "该平台公开发布能力仍在验证中",
        "platform_not_verified": "该平台公开发布能力仍在验证中",
        "publish_result_unconfirmed": "平台返回结果暂未确认，为避免重复发文已暂停此任务",
    }.get(code, "" if not code else "发布未完成，请稍后再试")


def publishing_state(*, user, subject_id) -> dict[str, Any]:
    subject = subject_for_user(user=user, subject_id=subject_id)
    preference = preference_for_subject(user=user, subject=subject)
    accounts = list(PlatformAccount.objects.filter(user=user, subject=subject))
    account_by_key = {item.platform_key: item for item in accounts}
    platforms = platform_payload(enabled_platform_keys())
    for platform in platforms:
        account = account_by_key.get(str(platform["key"]))
        platform["account"] = account_payload(account) if account else None

    recent_publications = list(
        Publication.objects.filter(user=user, subject=subject)
        .select_related("article")
        .prefetch_related("targets")[:20]
    )
    connected = sum(1 for item in accounts if item.status == PlatformAccount.Status.CONNECTED)
    account_needs_action = sum(
        1
        for item in accounts
        if item.status in {PlatformAccount.Status.EXPIRED, PlatformAccount.Status.ACTION_REQUIRED}
    )
    awaiting_review = PublicationTarget.objects.filter(
        publication__user=user,
        publication__subject=subject,
        status=PublicationTarget.Status.PAUSED,
        safe_error_code="awaiting_review",
    ).values("publication_id").distinct().count()
    today = timezone.localdate()
    today_targets = PublicationTarget.objects.filter(
        publication__user=user,
        publication__subject=subject,
        scheduled_at__date=today,
    )
    return {
        "subject": {
            "id": str(subject.id),
            "official_name": subject.current_version.official_name if subject.current_version else "当前主体",
        },
        "preference": preference_payload(preference),
        "summary": {
            "platform_count": len(platforms),
            "connected_count": connected,
            "needs_action_count": account_needs_action + awaiting_review,
            "today_plan_count": today_targets.count(),
            "today_published_count": today_targets.filter(status=PublicationTarget.Status.SUCCEEDED).count(),
        },
        "platforms": platforms,
        "recent_publications": [publication_payload(item) for item in recent_publications],
    }


@transaction.atomic
def update_preference(*, user, subject_id, values: dict[str, Any]) -> PublishingPreference:
    subject = subject_for_user(user=user, subject_id=subject_id)
    preference = preference_for_subject(user=user, subject=subject)
    expected_version = values.pop("expected_version", None)
    if expected_version is not None and expected_version != preference.version:
        raise PublishingInputError("设置已发生变化，请刷新后重新保存")
    custom_keys = values.get("custom_platform_keys")
    if custom_keys is not None:
        unknown = sorted(set(custom_keys) - set(PLATFORM_BY_KEY))
        if unknown:
            raise PublishingInputError("包含暂不支持的平台")
        values["custom_platform_keys"] = list(dict.fromkeys(custom_keys))
    for key, value in values.items():
        setattr(preference, key, value)
    preference.version += 1
    preference.save()
    return preference


@transaction.atomic
def create_authorization_session(*, user, subject_id, platform_key: str) -> tuple[PlatformAuthorizationSession, str]:
    subject = subject_for_user(user=user, subject_id=subject_id)
    definition = PLATFORM_BY_KEY.get(platform_key)
    if definition is None:
        raise PublishingInputError("暂不支持该平台")
    if platform_key not in enabled_platform_keys():
        raise PublishingInputError("该平台正在适配验证中，暂未开放授权")

    account, _ = PlatformAccount.objects.get_or_create(
        user=user,
        subject=subject,
        platform_key=platform_key,
        defaults={"auth_method": definition.auth_method},
    )
    account.auth_method = definition.auth_method
    account.status = PlatformAccount.Status.AUTHORIZING
    account.last_error_code = ""
    account.save(update_fields=("auth_method", "status", "last_error_code", "updated_at"))

    token, token_digest = issue_one_time_token()
    ttl = int(getattr(settings, "PUBLISHING_AUTH_SESSION_TTL_SECONDS", 900))
    session = PlatformAuthorizationSession.objects.create(
        user=user,
        subject=subject,
        account=account,
        platform_key=platform_key,
        auth_method=definition.auth_method,
        one_time_token_digest=token_digest,
        expires_at=timezone.now() + timedelta(seconds=ttl),
    )
    return session, token


@transaction.atomic
def complete_authorization_session(
    *,
    session: PlatformAuthorizationSession,
    secret_payload: dict[str, Any],
    display_name: str = "",
    external_account_id: str = "",
    session_expires_at=None,
) -> PlatformAccount:
    if session.expires_at <= timezone.now():
        session.status = PlatformAuthorizationSession.Status.EXPIRED
        session.safe_error_code = "authorization_timeout"
        session.save(update_fields=("status", "safe_error_code", "updated_at"))
        raise PublishingInputError("授权时间已结束，请重新授权")
    account = session.account
    if account is None:
        raise PublishingInputError("授权账号不存在")
    account.secret_ciphertext = encrypt_secret(secret_payload)
    account.display_name = display_name[:255]
    account.external_account_id = external_account_id[:255]
    account.session_expires_at = session_expires_at
    account.status = PlatformAccount.Status.CONNECTED
    account.last_checked_at = timezone.now()
    account.last_error_code = ""
    account.credential_version += 1
    account.save()
    session.status = PlatformAuthorizationSession.Status.SUCCEEDED
    session.completed_at = timezone.now()
    session.safe_error_code = ""
    session.save(update_fields=("status", "completed_at", "safe_error_code", "updated_at"))
    return account


@transaction.atomic
def disconnect_platform_account(*, user, subject_id, platform_key: str) -> None:
    subject = subject_for_user(user=user, subject_id=subject_id)
    account = get_object_or_404(PlatformAccount, user=user, subject=subject, platform_key=platform_key)
    account.secret_ciphertext = ""
    account.external_account_id = ""
    account.display_name = ""
    account.session_expires_at = None
    account.status = PlatformAccount.Status.UNLINKED
    account.enabled_for_auto = False
    account.last_error_code = ""
    account.credential_version += 1
    account.save()


def _connected_platform_keys(*, user, subject) -> set[str]:
    enabled = enabled_platform_keys()
    return {
        key
        for key in PlatformAccount.objects.filter(
            user=user,
            subject=subject,
            status=PlatformAccount.Status.CONNECTED,
            enabled_for_auto=True,
            platform_key__in=enabled,
        ).values_list("platform_key", flat=True)
    }


def _smart_platform_selection(article: Article, connected: set[str]) -> list[str]:
    ordered: list[str] = []

    def extend(keys) -> None:
        for key in keys:
            if key in PLATFORM_BY_KEY and key not in ordered:
                ordered.append(key)

    recommended = list(article.template_version.recommended_channel_keys) if article.template_version else []
    extend(key for key in recommended if key != "website")

    article_type_key = article.article_type.key if article.article_type_id and article.article_type else ""
    extend(_SMART_BY_ARTICLE_TYPE.get(article_type_key, ()))

    sample = f"{article.title}\n{article.content[:5000]}".lower()
    if any(cue in sample for cue in _TECH_CUES):
        extend(_SMART_TECH)
    if any(cue in sample for cue in _VISUAL_CUES):
        extend(_SMART_VISUAL)
    extend(_SMART_DEFAULT)

    selected = [key for key in ordered if key in connected]
    if not selected:
        selected = sorted(connected)
    # Smart mode deliberately avoids mechanical 17-platform flooding. Users can
    # still choose “所有已授权平台” when they explicitly want full distribution.
    return selected[:8]


@transaction.atomic
def create_publication(
    *, user, subject_id, article_id, platform_keys: list[str] | None = None, scheduled_at=None
) -> Publication:
    subject = subject_for_user(user=user, subject_id=subject_id)
    article = get_object_or_404(
        Article.objects.select_related("article_type", "template_version"),
        id=article_id,
        user=user,
        subject=subject,
    )
    if article.status != Article.Status.READY or not article.title.strip() or not article.content.strip():
        raise PublishingInputError("文章需要先完成生成并达到可发布状态")
    preference = preference_for_subject(user=user, subject=subject)
    connected = _connected_platform_keys(user=user, subject=subject)

    if platform_keys:
        requested = list(dict.fromkeys(platform_keys))
        selected = [key for key in requested if key in connected]
        if len(selected) != len([key for key in requested if key in PLATFORM_BY_KEY]):
            raise PublishingInputError("所选平台中包含未授权、已暂停或正在验证的平台")
    elif preference.distribution_strategy == PublishingPreference.DistributionStrategy.ALL:
        selected = sorted(connected)
    elif preference.distribution_strategy == PublishingPreference.DistributionStrategy.CUSTOM:
        selected = [key for key in list(preference.custom_platform_keys or []) if key in connected]
    else:
        selected = _smart_platform_selection(article, connected)

    selected = [key for key in selected if key in PLATFORM_BY_KEY]
    if not selected:
        raise PublishingInputError("请至少授权并启用一个可发布平台")

    digest = hashlib.sha256(article.content.encode("utf-8")).hexdigest()
    publication = Publication.objects.create(
        user=user,
        subject=subject,
        article=article,
        status=Publication.Status.QUEUED,
        source_title=article.title,
        source_content_digest=digest,
        distribution_strategy=preference.distribution_strategy,
        image_strategy=preference.image_strategy,
        image_plan={
            "strategy": preference.image_strategy,
            "density": preference.image_density,
            "customer_assets_first": preference.image_strategy != PublishingPreference.ImageStrategy.AI_AUTO,
            "allow_ai_supplement": preference.image_strategy != PublishingPreference.ImageStrategy.CUSTOMER_ONLY,
        },
        platform_plan=selected,
        scheduled_at=scheduled_at,
    )
    accounts = {
        item.platform_key: item
        for item in PlatformAccount.objects.filter(user=user, subject=subject, platform_key__in=selected)
    }
    for index, key in enumerate(selected):
        account = accounts.get(key)
        status = PublicationTarget.Status.WAITING
        if account is None or account.status != PlatformAccount.Status.CONNECTED:
            status = PublicationTarget.Status.AUTH_REQUIRED
        target_time = scheduled_at
        if scheduled_at is not None:
            target_time = scheduled_at + timedelta(minutes=35 * index)
        PublicationTarget.objects.create(
            publication=publication,
            account=account,
            platform_key=key,
            status=status,
            scheduled_at=target_time,
        )
    return publication
