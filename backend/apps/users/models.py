import uuid

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import PermissionsMixin
from django.db import models

from .managers import UserManager
from .phone_numbers import normalize_phone


class User(AbstractBaseUser, PermissionsMixin):
    class ApprovalStatus(models.TextChoices):
        PENDING = "pending", "待审核"
        APPROVED = "approved", "审核通过"
        REJECTED = "rejected", "审核拒绝"

    class AccountStatus(models.TextChoices):
        ACTIVE = "active", "正常"
        FROZEN = "frozen", "冻结"
        CANCEL_PENDING = "cancel_pending", "注销冷静期"
        CANCELLED = "cancelled", "已注销"

    ACTIVE_ACCOUNT_STATUSES = frozenset(
        {
            AccountStatus.ACTIVE,
            AccountStatus.CANCEL_PENDING,
        }
    )

    id: models.UUIDField = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phone: models.CharField = models.CharField(max_length=14, unique=True)
    nickname: models.CharField = models.CharField(max_length=50)
    approval_status: models.CharField = models.CharField(
        max_length=16,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING,
        db_index=True,
    )
    account_status: models.CharField = models.CharField(
        max_length=16,
        choices=AccountStatus.choices,
        default=AccountStatus.ACTIVE,
        db_index=True,
    )
    approval_reason: models.TextField = models.TextField(blank=True)
    approved_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)
    approved_by: models.ForeignKey = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_users",
    )
    session_version: models.PositiveBigIntegerField = models.PositiveBigIntegerField(default=1)
    status_version: models.PositiveBigIntegerField = models.PositiveBigIntegerField(default=1)
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
        APPROVAL = "approval", "审核状态"
        ACCOUNT = "account", "账号状态"

    class EventType(models.TextChoices):
        APPROVED = "approved", "审核通过"
        REJECTED = "rejected", "审核拒绝"
        RESUBMITTED = "resubmitted", "重新提交"
        FROZEN = "frozen", "账号冻结"
        UNFROZEN = "unfrozen", "账号解冻"

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
                condition=(
                    models.Q(
                        status_domain="approval",
                        from_value__in=["pending", "approved", "rejected"],
                        to_value__in=["pending", "approved", "rejected"],
                    )
                    | models.Q(
                        status_domain="account",
                        from_value__in=["active", "frozen", "cancel_pending", "cancelled"],
                        to_value__in=["active", "frozen", "cancel_pending", "cancelled"],
                    )
                ),
                name="status_event_domain_values_valid",
            )
        ]

    def __str__(self) -> str:
        return str(self.id)


class Notification(models.Model):
    class NotificationType(models.TextChoices):
        APPROVAL_APPROVED = "approval_approved", "审核通过"
        APPROVAL_REJECTED = "approval_rejected", "审核拒绝"
        ACCOUNT_FROZEN = "account_frozen", "账号冻结"
        ACCOUNT_UNFROZEN = "account_unfrozen", "账号解冻"
        PLAN_APPLICATION_SUBMITTED = "plan_application_submitted", "套餐申请已提交"
        PLAN_APPLICATION_CONTACTED = "plan_application_contacted", "套餐申请已联系"
        PLAN_APPLICATION_CLOSED = "plan_application_closed", "套餐申请已关闭"
        PLAN_APPLICATION_CANCELLED = "plan_application_cancelled", "套餐申请已取消"

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
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "notifications"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("recipient", "created_at"), name="notification_user_created_idx")
        ]

    def __str__(self) -> str:
        return str(self.id)
