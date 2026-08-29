import uuid

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import PermissionsMixin
from django.db import models

from .managers import UserManager
from .phone_numbers import normalize_phone


class Tenant(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        ACTIVE = "active", "启用"
        INACTIVE = "inactive", "停用"

    LEGACY_DEFAULT_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
    LEGACY_DEFAULT_KEY = "legacy-default"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.SlugField(max_length=80, unique=True)
    display_name = models.CharField(max_length=120)
    brand_name = models.CharField(max_length=120, blank=True)
    logo_reference = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenants"
        ordering = ("display_name", "id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=("active", "inactive")),
                name="tenant_valid_status",
            )
        ]

    @classmethod
    def legacy_default(cls):
        tenant, _ = cls.objects.get_or_create(
            id=cls.LEGACY_DEFAULT_ID,
            defaults={
                "key": cls.LEGACY_DEFAULT_KEY,
                "display_name": "默认租户",
                "brand_name": "显问 GEO",
            },
        )
        return tenant


class User(AbstractBaseUser, PermissionsMixin):
    class AccountStatus(models.TextChoices):
        ACTIVE = "active", "正常"
        FROZEN = "frozen", "禁用"
        CANCEL_PENDING = "cancel_pending", "注销冷静期"
        CANCELLED = "cancelled", "已注销"

    class AppearanceMode(models.TextChoices):
        LIGHT = "light", "浅色"
        DARK = "dark", "深色"
        SYSTEM = "system", "跟随系统"

    class AppearanceAccent(models.TextChoices):
        BLUE = "blue", "显问蓝"
        GREEN = "green", "青绿色"
        PURPLE = "purple", "紫罗兰"
        ORANGE = "orange", "暖橙色"

    ACTIVE_ACCOUNT_STATUSES = frozenset(
        {
            AccountStatus.ACTIVE,
            AccountStatus.CANCEL_PENDING,
        }
    )

    id: models.UUIDField = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="users",
    )
    phone: models.CharField = models.CharField(max_length=14, unique=True)
    nickname: models.CharField = models.CharField(max_length=50)
    appearance_mode: models.CharField = models.CharField(
        max_length=16,
        choices=AppearanceMode.choices,
        default=AppearanceMode.SYSTEM,
    )
    appearance_accent: models.CharField = models.CharField(
        max_length=16,
        choices=AppearanceAccent.choices,
        default=AppearanceAccent.BLUE,
    )
    account_status: models.CharField = models.CharField(
        max_length=16,
        choices=AccountStatus.choices,
        default=AccountStatus.ACTIVE,
        db_index=True,
    )
    session_version: models.PositiveBigIntegerField = models.PositiveBigIntegerField(default=1)
    status_version: models.PositiveBigIntegerField = models.PositiveBigIntegerField(default=1)
    is_test_account: models.BooleanField = models.BooleanField(default=False, db_index=True)
    is_staff: models.BooleanField = models.BooleanField(default=False)
    is_active: models.BooleanField = models.BooleanField(default=True)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = ["nickname"]

    class Meta:
        db_table = "users"
        ordering = ("-created_at",)
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        account_status__in=["active", "cancel_pending"],
                        is_active=True,
                    )
                    | models.Q(
                        account_status__in=["frozen", "cancelled"],
                        is_active=False,
                    )
                ),
                name="user_account_status_active_consistent",
            ),
            models.CheckConstraint(
                condition=models.Q(status_version__gte=1),
                name="user_status_version_gte_1",
            ),
            models.CheckConstraint(
                condition=models.Q(appearance_mode__in=("light", "dark", "system")),
                name="user_appearance_mode_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    appearance_accent__in=("blue", "green", "purple", "orange")
                ),
                name="user_appearance_accent_valid",
            ),
        ]

    def __str__(self) -> str:
        return str(self.id)

    def synchronize_active_state(self) -> None:
        self.is_active = self.account_status in self.ACTIVE_ACCOUNT_STATUSES

    def save(self, *args, **kwargs):
        self.phone = normalize_phone(self.phone)
        self.synchronize_active_state()
        return super().save(*args, **kwargs)


class LoginEvent(models.Model):
    class LoginMethod(models.TextChoices):
        PASSWORD = "password", "密码"
        SMS = "sms", "短信验证码"

    class FailureReason(models.TextChoices):
        INVALID_CREDENTIALS = "invalid_credentials", "凭证错误"
        INACTIVE_ACCOUNT = "inactive_account", "账号不可登录"
        RATE_LIMITED = "rate_limited", "登录受限"
        SERVICE_UNAVAILABLE = "service_unavailable", "认证服务不可用"

    id: models.UUIDField = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user: models.ForeignKey = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="login_events",
    )
    phone_fingerprint: models.CharField = models.CharField(max_length=64, db_index=True)
    login_method: models.CharField = models.CharField(max_length=16, choices=LoginMethod.choices)
    success: models.BooleanField = models.BooleanField(db_index=True)
    failure_reason: models.CharField = models.CharField(
        max_length=32,
        choices=FailureReason.choices,
        blank=True,
    )
    ip_address: models.GenericIPAddressField = models.GenericIPAddressField(null=True, blank=True)
    user_agent: models.CharField = models.CharField(max_length=512, blank=True)
    request_id: models.UUIDField = models.UUIDField(db_index=True)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "login_events"
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=("phone_fingerprint", "created_at"),
                name="login_phone_created_idx",
            )
        ]

    def __str__(self) -> str:
        return str(self.id)


class UserStatusEvent(models.Model):
    class StatusDomain(models.TextChoices):
        ACCOUNT = "account", "账号状态"

    class EventType(models.TextChoices):
        FROZEN = "frozen", "账号禁用"
        UNFROZEN = "unfrozen", "账号恢复"

    id: models.UUIDField = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user: models.ForeignKey = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="status_events",
    )
    status_domain: models.CharField = models.CharField(max_length=16, choices=StatusDomain.choices)
    event_type: models.CharField = models.CharField(max_length=16, choices=EventType.choices)
    from_value: models.CharField = models.CharField(max_length=16)
    to_value: models.CharField = models.CharField(max_length=16)
    reason: models.CharField = models.CharField(max_length=500, blank=True)
    actor: models.ForeignKey = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="performed_status_events",
    )
    request_id: models.UUIDField = models.UUIDField(db_index=True)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "user_status_events"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("user", "created_at"), name="status_user_created_idx"),
            models.Index(fields=("status_domain", "created_at"), name="status_domain_created_idx"),
            models.Index(fields=("event_type", "created_at"), name="status_event_created_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    status_domain="account",
                    from_value__in=["active", "frozen", "cancel_pending", "cancelled"],
                    to_value__in=["active", "frozen", "cancel_pending", "cancelled"],
                ),
                name="status_event_domain_values_valid",
            )
        ]

    def __str__(self) -> str:
        return str(self.id)


class Notification(models.Model):
    class NotificationType(models.TextChoices):
        ACCOUNT_FROZEN = "account_frozen", "账号禁用"
        ACCOUNT_UNFROZEN = "account_unfrozen", "账号恢复"
        PLAN_APPLICATION_SUBMITTED = "plan_application_submitted", "套餐申请已提交"
        PLAN_APPLICATION_CONTACTED = "plan_application_contacted", "套餐申请已联系"
        PLAN_APPLICATION_CLOSED = "plan_application_closed", "套餐申请已关闭"
        PLAN_APPLICATION_CANCELLED = "plan_application_cancelled", "套餐申请已取消"
        PLAN_APPLICATION_ACTIVATED = "plan_application_activated", "套餐申请已开通"
        SUBSCRIPTION_TRIAL_GRANTED = "subscription_trial_granted", "试用套餐已发放"
        SUBSCRIPTION_EXPIRED = "subscription_expired", "套餐已到期"
        SUBSCRIPTION_TERMINATED = "subscription_terminated", "套餐已终止"
        SUBSCRIPTION_RENEWED = "subscription_renewed", "Subscription renewed"
        SUBJECT_REVIEW_APPROVED = (
            "subject_review_approved",
            "\u4e3b\u4f53\u8d44\u6599\u5ba1\u6838\u901a\u8fc7",
        )
        SUBJECT_REVIEW_REJECTED = (
            "subject_review_rejected",
            "\u4e3b\u4f53\u8d44\u6599\u5ba1\u6838\u62d2\u7edd",
        )

        DOCUMENT_PARSE_SUCCEEDED = "document_parse_succeeded", "??????"
        DOCUMENT_PARSE_FAILED = "document_parse_failed", "??????"
        WEB_SOURCE_IMPORT_SUCCEEDED = "web_import_succeeded", "网页导入完成"
        WEB_SOURCE_IMPORT_FAILED = "web_import_failed", "网页导入失败"

    id: models.UUIDField = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient: models.ForeignKey = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    notification_type: models.CharField = models.CharField(
        max_length=32,
        choices=NotificationType.choices,
    )
    title: models.CharField = models.CharField(max_length=100)
    safe_summary: models.CharField = models.CharField(max_length=200)
    related_status_event: models.ForeignKey = models.ForeignKey(
        UserStatusEvent,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="notifications",
    )
    related_plan_application = models.ForeignKey(
        "plans.PlanApplication",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="notifications",
    )
    read_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)
    related_subscription = models.ForeignKey(
        "plans.Subscription",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="notifications",
    )
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "notifications"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("recipient", "created_at"), name="notification_user_created_idx")
        ]

    def __str__(self) -> str:
        return str(self.id)
