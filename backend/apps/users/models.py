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
            )
        ]

    def __str__(self) -> str:
        return str(self.id)

    def synchronize_active_state(self) -> None:
        self.is_active = self.account_status in self.ACTIVE_ACCOUNT_STATUSES

    def save(self, *args, **kwargs):
        self.phone = normalize_phone(self.phone)
        self.synchronize_active_state()
        return super().save(*args, **kwargs)

    def set_account_status(self, account_status: str) -> None:
        updated = type(self).objects.set_account_status(self.pk, account_status)
        self.account_status = updated.account_status
        self.is_active = updated.is_active
        self.updated_at = updated.updated_at


class LoginEvent(models.Model):
    class LoginMethod(models.TextChoices):
        PASSWORD = "password", "密码"

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
