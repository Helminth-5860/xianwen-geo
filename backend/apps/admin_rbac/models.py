import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class AdminRole(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        ACTIVE = "active", "启用"
        INACTIVE = "inactive", "停用"

    class DataScope(models.TextChoices):
        OWN = "own", "仅本人负责"
        ROLE = "role", "当前角色"
        ALL = "all", "全部客户"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=80, unique=True)
    description = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    data_scope = models.CharField(max_length=16, choices=DataScope.choices)
    version = models.PositiveBigIntegerField(default=1)
    require_sms_2fa = models.BooleanField(default=False)
    ip_allowlist_enabled = models.BooleanField(default=False)
    security_version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "admin_roles"
        ordering = ("name", "id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=("active", "inactive")),
                name="admin_role_valid_status",
            ),
            models.CheckConstraint(
                condition=models.Q(data_scope__in=("own", "role", "all")),
                name="admin_role_valid_scope",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1), name="admin_role_version_gte_1"
            ),
            models.CheckConstraint(
                condition=models.Q(security_version__gte=1),
                name="admin_role_security_version_gte_1",
            ),
        ]


class AdminPermission(models.Model):  # noqa: DJ008
    class PermissionType(models.TextChoices):
        MENU = "menu", "菜单"
        ACTION = "action", "动作"

    class Status(models.TextChoices):
        ACTIVE = "active", "启用"
        INACTIVE = "inactive", "停用"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=100)
    module = models.CharField(max_length=50)
    permission_type = models.CharField(max_length=16, choices=PermissionType.choices)
    description = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    sort_order = models.PositiveIntegerField(default=0)
    superuser_only = models.BooleanField(default=False)

    class Meta:
        db_table = "admin_permissions"
        ordering = ("sort_order", "key")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(permission_type__in=("menu", "action")),
                name="admin_permission_valid_type",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("active", "inactive")),
                name="admin_permission_valid_status",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk and not self._state.adding:
            previous_status = (
                type(self).objects.filter(pk=self.pk).values_list("status", flat=True).first()
            )
            if previous_status is not None and previous_status != self.status:
                raise ValidationError(
                    "权限状态必须通过 admin_rbac.services.set_permission_status() 修改。"
                )
        return super().save(*args, **kwargs)


class AdminProfile(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        ACTIVE = "active", "启用"
        DISABLED = "disabled", "停用"
        LOCKED = "locked", "锁定"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    registration_channel_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="admin_profile"
    )
    admin_status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )
    role = models.ForeignKey(
        AdminRole, null=True, blank=True, on_delete=models.PROTECT, related_name="admin_profiles"
    )
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "admin_profiles"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(admin_status__in=("active", "disabled", "locked")),
                name="admin_profile_valid_status",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1), name="admin_profile_version_gte_1"
            ),
        ]


class AdminRolePermission(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.ForeignKey(AdminRole, on_delete=models.CASCADE, related_name="permission_links")
    permission = models.ForeignKey(
        AdminPermission, on_delete=models.PROTECT, related_name="role_links"
    )

    class Meta:
        db_table = "admin_role_permissions"
        constraints = [
            models.UniqueConstraint(
                fields=("role", "permission"), name="admin_role_permission_unique"
            )
        ]


class CustomerAssignment(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="customer_assignment"
    )
    owner_admin = models.ForeignKey(
        AdminProfile,
        on_delete=models.PROTECT,
        related_name="customer_assignments",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_customers",
    )
    assigned_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "customer_assignments"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(version__gte=1), name="customer_assignment_version_gte_1"
            )
        ]

    def save(self, *args, **kwargs):
        # Ownership is an authorization boundary, so invalid ADMIN/USER links
        # must not be persistable through ordinary ORM writes outside services.
        self.full_clean()
        return super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        errors = {}
        if self.customer_id:
            customer = self.customer
            if customer.is_staff or customer.is_superuser:
                errors["customer"] = "只有 USER 可以建立 ADMIN 归属。"
        if self.owner_admin_id:
            owner = self.owner_admin
            if owner.user.is_superuser or owner.role_id is None:
                errors["owner_admin"] = "USER 必须归属一个有效的非超级管理员 ADMIN。"
        if errors:
            raise ValidationError(errors)


class AdminRbacEvent(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="admin_rbac_events",
    )
    target_type = models.CharField(max_length=32)
    target_id = models.UUIDField()
    event_type = models.CharField(max_length=50, db_index=True)
    safe_before = models.JSONField(default=dict)
    safe_after = models.JSONField(default=dict)
    request_id = models.UUIDField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "admin_rbac_events"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("target_type", "target_id", "created_at"), name="rbac_target_idx")
        ]


class IpAllowlistStatus(models.TextChoices):
    ACTIVE = "active", "启用"
    INACTIVE = "inactive", "停用"


class RoleIpAllowlistEntry(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.ForeignKey(
        AdminRole, on_delete=models.CASCADE, related_name="ip_allowlist_entries"
    )
    network_cidr = models.CharField(max_length=64)
    ip_version = models.PositiveSmallIntegerField()
    label = models.CharField(max_length=100, blank=True)
    status = models.CharField(
        max_length=16, choices=IpAllowlistStatus.choices, default=IpAllowlistStatus.ACTIVE
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "admin_role_ip_allowlist_entries"
        ordering = ("network_cidr", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("role", "network_cidr"), name="admin_role_ip_cidr_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(ip_version__in=(4, 6)), name="admin_role_ip_version_valid"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("active", "inactive")),
                name="admin_role_ip_status_valid",
            ),
        ]


class SuperuserSecurityPolicy(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="superuser_security_policy",
    )
    ip_allowlist_enabled = models.BooleanField(default=False)
    security_version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "superuser_security_policies"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(security_version__gte=1),
                name="superuser_security_version_gte_1",
            )
        ]


class SuperuserIpAllowlistEntry(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    policy = models.ForeignKey(
        SuperuserSecurityPolicy,
        on_delete=models.CASCADE,
        related_name="ip_allowlist_entries",
    )
    network_cidr = models.CharField(max_length=64)
    ip_version = models.PositiveSmallIntegerField()
    label = models.CharField(max_length=100, blank=True)
    status = models.CharField(
        max_length=16, choices=IpAllowlistStatus.choices, default=IpAllowlistStatus.ACTIVE
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "superuser_ip_allowlist_entries"
        ordering = ("network_cidr", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("policy", "network_cidr"), name="superuser_ip_cidr_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(ip_version__in=(4, 6)), name="superuser_ip_version_valid"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("active", "inactive")),
                name="superuser_ip_status_valid",
            ),
        ]


class AdminSecurityEvent(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="admin_security_events_as_actor",
    )
    subject = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="admin_security_events_as_subject",
    )
    event_type = models.CharField(max_length=64, db_index=True)
    request_id = models.UUIDField(db_index=True)
    ip_fingerprint = models.CharField(max_length=64, blank=True)
    user_agent_digest = models.CharField(max_length=64, blank=True)
    admin_profile_version = models.PositiveBigIntegerField(null=True, blank=True)
    role_version = models.PositiveBigIntegerField(null=True, blank=True)
    role_security_version = models.PositiveBigIntegerField(null=True, blank=True)
    policy_version = models.PositiveBigIntegerField(null=True, blank=True)
    stable_failure_reason = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "admin_security_events"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("subject", "created_at"), name="admin_sec_subject_idx"),
            models.Index(fields=("event_type", "created_at"), name="admin_sec_event_idx"),
        ]


# Imported here so Django discovers the XW-0107 models under this application.
from .risk_models import AuditEvent, RiskAction, RiskPolicy  # noqa: E402,F401
