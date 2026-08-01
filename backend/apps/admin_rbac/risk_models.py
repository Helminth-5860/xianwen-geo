import uuid

from django.conf import settings
from django.db import models


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError("追加式审计事件不允许更新。")

    def delete(self):
        raise TypeError("追加式审计事件不允许删除。")


class RiskAction(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        ACTIVE = "active", "启用"
        INACTIVE = "inactive", "停用"

    key = models.CharField(primary_key=True, max_length=100)
    name = models.CharField(max_length=100)
    module = models.CharField(max_length=50)
    target_type = models.CharField(max_length=50)
    supported_modes = models.JSONField(default=list)
    default_mode = models.CharField(max_length=16)
    minimum_mode = models.CharField(max_length=16)
    handler_key = models.CharField(max_length=100)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    catalog_version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "risk_actions"
        ordering = ("module", "key")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=("active", "inactive")),
                name="risk_action_valid_status",
            ),
            models.CheckConstraint(
                condition=models.Q(catalog_version__gte=1),
                name="risk_action_catalog_version_gte_1",
            ),
        ]


class RiskPolicy(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    action = models.OneToOneField(RiskAction, on_delete=models.PROTECT, related_name="policy")
    current_mode = models.CharField(max_length=16)
    version = models.PositiveBigIntegerField(default=1)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_risk_policies",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "risk_policies"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(version__gte=1), name="risk_policy_version_gte_1"
            ),
            models.CheckConstraint(
                condition=models.Q(current_mode__in=("confirm", "password", "two_person")),
                name="risk_policy_valid_mode",
            ),
        ]


class ApprovalRequest(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        PENDING = "pending", "待审批"
        REJECTED = "rejected", "已拒绝"
        CANCELLED = "cancelled", "已取消"
        EXPIRED = "expired", "已过期"
        STALE = "stale", "已失效"
        EXECUTED = "executed", "已执行"
        EXECUTION_FAILED = "execution_failed", "执行失败"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    action = models.ForeignKey(RiskAction, on_delete=models.PROTECT, related_name="approvals")
    action_key = models.CharField(max_length=100)
    policy_version = models.PositiveBigIntegerField()
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="requested_approvals"
    )
    target_type = models.CharField(max_length=50)
    target_id = models.UUIDField()
    target_version = models.PositiveBigIntegerField(default=0)
    sanitized_payload = models.JSONField(default=dict)
    payload_digest = models.CharField(max_length=64)
    safe_summary = models.CharField(max_length=500)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PENDING)
    expires_at = models.DateTimeField()
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_risk_requests",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="rejected_risk_requests",
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=500, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    execution_result = models.JSONField(default=dict)
    stable_error_code = models.CharField(max_length=64, blank=True)
    request_id = models.UUIDField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "approval_requests"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("status", "expires_at"), name="approval_status_expiry_idx"),
            models.Index(fields=("requester", "created_at"), name="approval_requester_idx"),
            models.Index(fields=("target_type", "target_id"), name="approval_target_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(target_version__gte=0), name="approval_target_version_gte_0"
            ),
            models.CheckConstraint(
                condition=~models.Q(approved_by=models.F("requester")),
                name="approval_requester_not_approver",
            ),
            models.CheckConstraint(
                condition=~models.Q(rejected_by=models.F("requester")),
                name="approval_requester_not_rejecter",
            ),
            models.CheckConstraint(
                condition=models.Q(expires_at__gt=models.F("created_at")),
                name="approval_expiry_after_created",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status="pending",
                        approved_by__isnull=True,
                        approved_at__isnull=True,
                        rejected_by__isnull=True,
                        rejected_at__isnull=True,
                        cancelled_at__isnull=True,
                        executed_at__isnull=True,
                    )
                    | models.Q(
                        status="rejected",
                        approved_by__isnull=True,
                        approved_at__isnull=True,
                        rejected_by__isnull=False,
                        rejected_at__isnull=False,
                        cancelled_at__isnull=True,
                        executed_at__isnull=True,
                    )
                    | models.Q(
                        status="cancelled",
                        approved_by__isnull=True,
                        approved_at__isnull=True,
                        rejected_by__isnull=True,
                        rejected_at__isnull=True,
                        cancelled_at__isnull=False,
                        executed_at__isnull=True,
                    )
                    | models.Q(
                        status__in=("expired", "stale"),
                        approved_by__isnull=True,
                        approved_at__isnull=True,
                        rejected_by__isnull=True,
                        rejected_at__isnull=True,
                        cancelled_at__isnull=True,
                        executed_at__isnull=True,
                    )
                    | models.Q(
                        status__in=("executed", "execution_failed"),
                        approved_by__isnull=False,
                        approved_at__isnull=False,
                        rejected_by__isnull=True,
                        rejected_at__isnull=True,
                        cancelled_at__isnull=True,
                        executed_at__isnull=False,
                    )
                ),
                name="approval_status_times_consistent",
            ),
            models.UniqueConstraint(
                fields=("requester", "action", "target_type", "target_id", "payload_digest"),
                condition=models.Q(status="pending"),
                name="approval_unique_pending_payload",
            ),
        ]


class AuditEvent(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.CharField(max_length=50, db_index=True)
    action_key = models.CharField(max_length=100, db_index=True)
    outcome = models.CharField(max_length=32, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events_as_actor",
    )
    subject = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events_as_subject",
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events_as_requester",
    )
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events_as_approver",
    )
    target_type = models.CharField(max_length=50)
    target_id = models.UUIDField()
    request_id = models.UUIDField(db_index=True)
    approval_request = models.ForeignKey(
        ApprovalRequest,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="audit_events",
    )
    safe_before = models.JSONField(default=dict)
    safe_after = models.JSONField(default=dict)
    stable_error_code = models.CharField(max_length=64, blank=True)
    ip_fingerprint = models.CharField(max_length=64, blank=True)
    user_agent_digest = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        db_table = "audit_events"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(
                fields=("target_type", "target_id", "created_at"), name="audit_target_idx"
            ),
            models.Index(fields=("actor", "created_at"), name="audit_actor_idx"),
        ]

    def save(self, *args, **kwargs):
        if self.pk and not self._state.adding:
            raise TypeError("追加式审计事件不允许更新。")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("追加式审计事件不允许删除。")
