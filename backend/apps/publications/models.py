from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class PublicationPlatform(models.Model):  # noqa: DJ008
    class AuthMode(models.TextChoices):
        BROWSER_QR = "browser_qr", "浏览器扫码"
        OFFICIAL_CREDENTIALS = "official_credentials", "官方凭据"
        HYBRID = "hybrid", "混合授权"

    class PublishMode(models.TextChoices):
        BROWSER = "browser", "浏览器发布"
        OFFICIAL_API = "official_api", "官方接口"
        HYBRID = "hybrid", "混合发布"

    class ValidationStatus(models.TextChoices):
        AVAILABLE = "available", "可用"
        TESTING = "testing", "正在验证"
        PAUSED = "paused", "已暂停"

    class HealthStatus(models.TextChoices):
        HEALTHY = "healthy", "正常"
        DEGRADED = "degraded", "部分异常"
        UNAVAILABLE = "unavailable", "暂不可用"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    channel = models.OneToOneField(
        "articles.PublishingChannel",
        on_delete=models.PROTECT,
        related_name="publication_platform",
    )
    auth_mode = models.CharField(max_length=32, choices=AuthMode.choices)
    publish_mode = models.CharField(max_length=32, choices=PublishMode.choices)
    validation_status = models.CharField(
        max_length=16, choices=ValidationStatus.choices, default=ValidationStatus.TESTING
    )
    health_status = models.CharField(
        max_length=16, choices=HealthStatus.choices, default=HealthStatus.HEALTHY
    )
    login_url = models.TextField()
    publish_url = models.TextField(blank=True)
    capabilities = models.JSONField(default=dict)
    minimum_interval_minutes = models.PositiveIntegerField(default=30)
    consecutive_failures = models.PositiveIntegerField(default=0)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_failure_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "publication_platforms"
        ordering = ("channel__sort_order", "channel__key")


class PlatformAccount(models.Model):  # noqa: DJ008
    class AuthStatus(models.TextChoices):
        AUTHORIZING = "authorizing", "授权中"
        AUTHORIZED = "authorized", "已授权"
        EXPIRED = "expired", "授权已失效"
        NEEDS_VERIFICATION = "needs_verification", "需要重新验证"
        REVOKED = "revoked", "已解除授权"
        FAILED = "failed", "授权失败"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="publication_accounts"
    )
    subject = models.ForeignKey(
        "subjects.Subject", on_delete=models.PROTECT, related_name="publication_accounts"
    )
    platform = models.ForeignKey(
        PublicationPlatform, on_delete=models.PROTECT, related_name="accounts"
    )
    display_name = models.CharField(max_length=200, blank=True)
    external_account_id = models.CharField(max_length=200, blank=True)
    auth_method = models.CharField(max_length=32)
    auth_status = models.CharField(
        max_length=32, choices=AuthStatus.choices, default=AuthStatus.AUTHORIZING
    )
    encrypted_auth_state = models.TextField(blank=True)
    auth_metadata = models.JSONField(default=dict)
    enabled_for_auto_publish = models.BooleanField(default=True)
    is_default = models.BooleanField(default=True)
    authorized_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    last_auth_check_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "publication_accounts"
        ordering = ("platform__channel__sort_order", "created_at")
        indexes = [
            models.Index(
                fields=("user", "subject", "auth_status"), name="pub_account_owner_status_idx"
            )
        ]
        constraints = [
            models.CheckConstraint(condition=Q(version__gte=1), name="pub_account_version_gte_1"),
            models.UniqueConstraint(
                fields=("user", "subject", "platform"),
                condition=Q(is_default=True),
                name="pub_account_one_default",
            ),
        ]


class AuthorizationSession(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        QUEUED = "queued", "准备授权"
        WAITING = "waiting", "等待扫码"
        AUTHORIZED = "authorized", "授权成功"
        NEEDS_INTERACTION = "needs_interaction", "需要额外验证"
        EXPIRED = "expired", "授权已过期"
        FAILED = "failed", "授权失败"
        CANCELLED = "cancelled", "已取消"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="authorization_sessions"
    )
    subject = models.ForeignKey(
        "subjects.Subject", on_delete=models.PROTECT, related_name="authorization_sessions"
    )
    platform = models.ForeignKey(
        PublicationPlatform, on_delete=models.PROTECT, related_name="authorization_sessions"
    )
    account = models.ForeignKey(
        PlatformAccount,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="authorization_sessions",
    )
    auth_method = models.CharField(max_length=32)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.QUEUED)
    login_snapshot_data_url = models.TextField(blank=True)
    safe_error_code = models.CharField(max_length=100, blank=True)
    expires_at = models.DateTimeField()
    last_snapshot_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "publication_authorization_sessions"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("status", "expires_at"), name="pub_auth_status_expiry_idx")
        ]


class AutoPublishPolicy(models.Model):  # noqa: DJ008
    class OperatingMode(models.TextChoices):
        MANAGED = "managed", "全自动托管"
        REVIEW = "review", "审核后发布"
        SELECTED = "selected", "仅发布指定内容"

    class DistributionStrategy(models.TextChoices):
        SMART = "smart", "智能分发"
        ALL_AUTHORIZED = "all_authorized", "所有已授权平台"
        CUSTOM = "custom", "自定义平台"

    class FrequencyMode(models.TextChoices):
        SMART = "smart", "智能安排"
        DAILY_1 = "daily_1", "每天 1 篇"
        DAILY_2 = "daily_2", "每天 2 篇"
        DAILY_3 = "daily_3", "每天 3 篇"
        CUSTOM = "custom", "自定义"

    class ImageStrategy(models.TextChoices):
        CUSTOMER_ONLY = "customer_only", "仅使用企业素材"
        PREFER_CUSTOMER = "prefer_customer", "企业素材优先，不足自动补图"
        AUTO = "auto", "全自动配图"

    class ImageRichness(models.TextChoices):
        SIMPLE = "simple", "简洁"
        STANDARD = "standard", "标准"
        RICH = "rich", "丰富"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="auto_publish_policies"
    )
    subject = models.ForeignKey(
        "subjects.Subject", on_delete=models.PROTECT, related_name="auto_publish_policies"
    )
    enabled = models.BooleanField(default=False)
    operating_mode = models.CharField(
        max_length=16, choices=OperatingMode.choices, default=OperatingMode.MANAGED
    )
    distribution_strategy = models.CharField(
        max_length=24, choices=DistributionStrategy.choices, default=DistributionStrategy.SMART
    )
    custom_platform_keys = models.JSONField(default=list)
    frequency_mode = models.CharField(
        max_length=16, choices=FrequencyMode.choices, default=FrequencyMode.SMART
    )
    custom_daily_limit = models.PositiveSmallIntegerField(default=1)
    image_strategy = models.CharField(
        max_length=24, choices=ImageStrategy.choices, default=ImageStrategy.PREFER_CUSTOMER
    )
    image_richness = models.CharField(
        max_length=16, choices=ImageRichness.choices, default=ImageRichness.STANDARD
    )
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "auto_publish_policies"
        constraints = [
            models.UniqueConstraint(fields=("user", "subject"), name="auto_publish_policy_unique"),
            models.CheckConstraint(condition=Q(version__gte=1), name="auto_publish_policy_version_gte_1"),
            models.CheckConstraint(
                condition=Q(custom_daily_limit__gte=1, custom_daily_limit__lte=20),
                name="auto_publish_daily_limit_range",
            ),
        ]


class PublicationJob(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        PLANNING = "planning", "正在规划"
        PREPARING = "preparing", "正在准备"
        SCHEDULED = "scheduled", "等待发布"
        PUBLISHING = "publishing", "发布中"
        SUCCEEDED = "succeeded", "已完成"
        PARTIAL = "partial", "部分完成"
        FAILED = "failed", "发布失败"
        CANCELLED = "cancelled", "已取消"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="publication_jobs"
    )
    subject = models.ForeignKey(
        "subjects.Subject", on_delete=models.PROTECT, related_name="publication_jobs"
    )
    article = models.ForeignKey(
        "articles.Article", on_delete=models.PROTECT, related_name="publication_jobs"
    )
    policy = models.ForeignKey(
        AutoPublishPolicy, on_delete=models.PROTECT, related_name="publication_jobs"
    )
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PLANNING)
    policy_snapshot = models.JSONField(default=dict)
    distribution_plan = models.JSONField(default=dict)
    visual_plan = models.JSONField(default=dict)
    idempotency_key_digest = models.CharField(max_length=64, unique=True)
    safe_error_code = models.CharField(max_length=100, blank=True)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "publication_jobs"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("user", "status", "created_at"), name="pub_job_owner_status_idx")
        ]


class PublicationTarget(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        WAITING = "waiting", "等待准备"
        ADAPTING = "adapting", "正在适配"
        READY = "ready", "准备完成"
        SCHEDULED = "scheduled", "等待发布"
        PUBLISHING = "publishing", "发布中"
        PUBLISHED = "published", "已发布"
        FAILED = "failed", "发布失败"
        REQUIRES_AUTH = "requires_auth", "需要重新授权"
        SKIPPED = "skipped", "已跳过"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(PublicationJob, on_delete=models.PROTECT, related_name="targets")
    platform = models.ForeignKey(
        PublicationPlatform, on_delete=models.PROTECT, related_name="publication_targets"
    )
    account = models.ForeignKey(
        PlatformAccount, on_delete=models.PROTECT, related_name="publication_targets"
    )
    adaptation = models.ForeignKey(
        "articles.ChannelAdaptation",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="publication_targets",
    )
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.WAITING)
    payload_snapshot = models.JSONField(default=dict)
    image_plan = models.JSONField(default=dict)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    external_post_id = models.CharField(max_length=300, blank=True)
    public_url = models.TextField(blank=True)
    attempts = models.PositiveIntegerField(default=0)
    safe_error_code = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "publication_targets"
        ordering = ("scheduled_at", "created_at")
        constraints = [
            models.UniqueConstraint(fields=("job", "platform"), name="publication_target_unique")
        ]
        indexes = [
            models.Index(fields=("status", "scheduled_at"), name="pub_target_schedule_idx")
        ]


class PublicationVisual(models.Model):  # noqa: DJ008
    class Role(models.TextChoices):
        COVER = "cover", "封面"
        ILLUSTRATION = "illustration", "正文插图"
        THUMBNAIL = "thumbnail", "平台缩略图"
        CARD = "card", "信息卡图"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(PublicationJob, on_delete=models.PROTECT, related_name="visuals")
    target = models.ForeignKey(
        PublicationTarget,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="visuals",
    )
    image = models.ForeignKey(
        "images.ImageAsset", on_delete=models.PROTECT, related_name="publication_visuals"
    )
    role = models.CharField(max_length=24, choices=Role.choices)
    ordinal = models.PositiveSmallIntegerField(default=0)
    section_hint = models.CharField(max_length=200, blank=True)
    source_strategy = models.CharField(max_length=32)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "publication_visuals"
        ordering = ("role", "ordinal", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("job", "target", "image", "role", "ordinal"),
                name="publication_visual_unique",
            )
        ]
