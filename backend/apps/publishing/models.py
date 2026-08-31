from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class PublishingPreference(models.Model):  # noqa: DJ008
    class Mode(models.TextChoices):
        MANAGED = "managed", "全自动托管"
        REVIEW = "review", "审核后发布"
        SELECTED = "selected", "仅发布指定内容"

    class DistributionStrategy(models.TextChoices):
        SMART = "smart", "智能分发"
        ALL = "all", "所有已授权平台"
        CUSTOM = "custom", "自定义平台"

    class ImageStrategy(models.TextChoices):
        CUSTOMER_ONLY = "customer_only", "仅使用企业素材"
        CUSTOMER_FIRST = "customer_first", "企业素材优先，不足自动补图"
        AI_AUTO = "ai_auto", "全自动配图"

    class ImageDensity(models.TextChoices):
        COMPACT = "compact", "简洁"
        STANDARD = "standard", "标准"
        RICH = "rich", "丰富"

    class FrequencyMode(models.TextChoices):
        SMART = "smart", "智能安排"
        FIXED = "fixed", "固定频率"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="publishing_preferences",
    )
    subject = models.OneToOneField(
        "subjects.Subject",
        on_delete=models.PROTECT,
        related_name="publishing_preference",
    )
    is_enabled = models.BooleanField(default=False)
    mode = models.CharField(max_length=16, choices=Mode.choices, default=Mode.MANAGED)
    distribution_strategy = models.CharField(
        max_length=16,
        choices=DistributionStrategy.choices,
        default=DistributionStrategy.SMART,
    )
    custom_platform_keys = models.JSONField(default=list)
    image_strategy = models.CharField(
        max_length=24,
        choices=ImageStrategy.choices,
        default=ImageStrategy.CUSTOMER_FIRST,
    )
    image_density = models.CharField(
        max_length=16,
        choices=ImageDensity.choices,
        default=ImageDensity.STANDARD,
    )
    frequency_mode = models.CharField(
        max_length=16,
        choices=FrequencyMode.choices,
        default=FrequencyMode.SMART,
    )
    posts_per_day = models.PositiveSmallIntegerField(default=1)
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "publishing_preferences"
        indexes = [models.Index(fields=("user", "is_enabled"), name="publishing_pref_user_idx")]
        constraints = [
            models.CheckConstraint(
                condition=Q(posts_per_day__gte=1, posts_per_day__lte=10),
                name="publishing_posts_day_range",
            ),
            models.CheckConstraint(
                condition=Q(version__gte=1), name="publishing_pref_version_gte_1"
            ),
        ]


class PlatformAccount(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        UNLINKED = "unlinked", "未授权"
        AUTHORIZING = "authorizing", "授权中"
        CONNECTED = "connected", "已授权"
        EXPIRED = "expired", "授权已失效"
        ACTION_REQUIRED = "action_required", "需要重新授权"
        SUSPENDED = "suspended", "已暂停"

    class AuthMethod(models.TextChoices):
        OFFICIAL_API = "official_api", "官方授权"
        BROWSER_SESSION = "browser_session", "网页登录授权"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="publishing_platform_accounts",
    )
    subject = models.ForeignKey(
        "subjects.Subject",
        on_delete=models.PROTECT,
        related_name="publishing_platform_accounts",
    )
    platform_key = models.CharField(max_length=32)
    auth_method = models.CharField(max_length=24, choices=AuthMethod.choices)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.UNLINKED)
    display_name = models.CharField(max_length=255, blank=True)
    external_account_id = models.CharField(max_length=255, blank=True)
    secret_ciphertext = models.TextField(blank=True)
    credential_version = models.PositiveIntegerField(default=1)
    enabled_for_auto = models.BooleanField(default=True)
    session_expires_at = models.DateTimeField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "publishing_platform_accounts"
        ordering = ("platform_key", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("user", "subject", "platform_key"),
                name="publishing_account_user_subject_platform_unique",
            ),
        ]
        indexes = [
            models.Index(fields=("user", "subject", "status"), name="publishing_account_state_idx"),
        ]


class PlatformAuthorizationSession(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        CREATED = "created", "等待授权"
        STARTING = "starting", "正在打开授权页面"
        WAITING_USER = "waiting_user", "等待完成登录"
        SUCCEEDED = "succeeded", "授权成功"
        FAILED = "failed", "授权未完成"
        EXPIRED = "expired", "授权已过期"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="publishing_authorization_sessions",
    )
    subject = models.ForeignKey(
        "subjects.Subject",
        on_delete=models.PROTECT,
        related_name="publishing_authorization_sessions",
    )
    account = models.ForeignKey(
        PlatformAccount,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="authorization_sessions",
    )
    platform_key = models.CharField(max_length=32)
    auth_method = models.CharField(max_length=24, choices=PlatformAccount.AuthMethod.choices)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.CREATED)
    one_time_token_digest = models.CharField(max_length=64, unique=True)
    remote_session_ref = models.CharField(max_length=255, blank=True)
    action_url = models.TextField(blank=True)
    safe_error_code = models.CharField(max_length=100, blank=True)
    expires_at = models.DateTimeField()
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "publishing_authorization_sessions"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("user", "status", "created_at"), name="publishing_auth_user_idx"),
            models.Index(
                fields=("platform_key", "status", "created_at"), name="publishing_auth_platform_idx"
            ),
        ]


class Publication(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        PREPARING = "preparing", "准备中"
        QUEUED = "queued", "等待发布"
        RUNNING = "running", "正在发布"
        PAUSED = "paused", "已暂停"
        PARTIAL = "partial", "部分完成"
        SUCCEEDED = "succeeded", "发布完成"
        FAILED = "failed", "发布未完成"
        CANCELLED = "cancelled", "已取消"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="publications"
    )
    subject = models.ForeignKey(
        "subjects.Subject", on_delete=models.PROTECT, related_name="publications"
    )
    article = models.ForeignKey(
        "articles.Article", on_delete=models.PROTECT, related_name="publications"
    )
    quota_hold = models.OneToOneField(
        "quotas.QuotaHoldGroup",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="publication",
    )
    request_id = models.UUIDField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PREPARING)
    source_title = models.CharField(max_length=500)
    source_content_digest = models.CharField(max_length=64)
    distribution_strategy = models.CharField(
        max_length=16, choices=PublishingPreference.DistributionStrategy.choices
    )
    image_strategy = models.CharField(
        max_length=24, choices=PublishingPreference.ImageStrategy.choices
    )
    image_plan = models.JSONField(default=dict)
    platform_plan = models.JSONField(default=list)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "publications"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("user", "subject", "status"), name="publication_user_state_idx")
        ]


class PublicationTarget(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        WAITING = "waiting", "等待发布"
        READY = "ready", "已准备"
        RUNNING = "running", "正在发布"
        SUBMITTED = "submitted", "平台审核中"
        SUCCEEDED = "succeeded", "已发布"
        FAILED = "failed", "发布失败"
        AUTH_REQUIRED = "auth_required", "需要重新授权"
        PAUSED = "paused", "已暂停"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    publication = models.ForeignKey(Publication, on_delete=models.PROTECT, related_name="targets")
    account = models.ForeignKey(
        PlatformAccount,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="publication_targets",
    )
    platform_key = models.CharField(max_length=32)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.WAITING)
    adapted_title = models.CharField(max_length=500, blank=True)
    adapted_content = models.TextField(blank=True)
    media_payload = models.JSONField(default=dict)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    external_post_id = models.CharField(max_length=255, blank=True)
    management_url = models.TextField(blank=True)
    public_url = models.TextField(blank=True)
    next_status_check_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    safe_error_code = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "publication_targets"
        ordering = ("scheduled_at", "platform_key")
        constraints = [
            models.UniqueConstraint(
                fields=("publication", "platform_key"), name="publication_target_platform_unique"
            ),
        ]
        indexes = [
            models.Index(fields=("status", "scheduled_at"), name="publication_target_queue_idx")
        ]
