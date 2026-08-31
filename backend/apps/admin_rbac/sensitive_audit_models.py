import uuid

from django.db import models


class SensitiveAuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError("敏感审计日志不允许更新。")

    def delete(self):
        raise TypeError("敏感审计日志不允许人工删除。")


class SensitiveAuditLog(models.Model):  # noqa: DJ008
    class Outcome(models.TextChoices):
        SUCCESS = "success", "成功"
        FAILURE = "failure", "失败"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.CharField(max_length=50, default="sensitive_action", db_index=True)
    action_key = models.CharField(max_length=100, db_index=True)
    outcome = models.CharField(max_length=16, choices=Outcome.choices, db_index=True)
    channel = models.CharField(max_length=32, default="admin_console")

    actor_user_id_snapshot = models.UUIDField(null=True, blank=True, db_index=True)
    actor_name_snapshot = models.CharField(max_length=50, blank=True)
    actor_role_snapshot = models.CharField(max_length=100, blank=True)
    actor_tenant_id_snapshot = models.UUIDField(null=True, blank=True)
    actor_tenant_name_snapshot = models.CharField(max_length=120, blank=True)

    target_user_id_snapshot = models.UUIDField(null=True, blank=True, db_index=True)
    target_name_snapshot = models.CharField(max_length=50, blank=True)
    target_tenant_id_snapshot = models.UUIDField(null=True, blank=True)
    target_tenant_name_snapshot = models.CharField(max_length=120, blank=True)

    quota_type = models.CharField(max_length=100, blank=True)
    quota_before = models.BigIntegerField(null=True, blank=True)
    quota_requested_delta = models.BigIntegerField(null=True, blank=True)
    quota_delta = models.BigIntegerField(null=True, blank=True)
    quota_after = models.BigIntegerField(null=True, blank=True)
    ledger_entry_id = models.UUIDField(null=True, blank=True, db_index=True)

    request_id = models.UUIDField(db_index=True)
    operation_ip = models.GenericIPAddressField(null=True, blank=True)
    login_ip_snapshot = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    safe_reason = models.CharField(max_length=500, blank=True)
    failure_reason = models.CharField(max_length=128, blank=True)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = SensitiveAuditQuerySet.as_manager()

    class Meta:
        db_table = "sensitive_audit_logs"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(
                fields=("actor_user_id_snapshot", "created_at"), name="sens_actor_created_idx"
            ),
            models.Index(
                fields=("target_user_id_snapshot", "created_at"), name="sens_target_created_idx"
            ),
            models.Index(fields=("action_key", "created_at"), name="sens_action_created_idx"),
            models.Index(fields=("operation_ip", "created_at"), name="sens_ip_created_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(outcome__in=("success", "failure")),
                name="sensitive_audit_valid_outcome",
            )
        ]

    def save(self, *args, **kwargs):
        if self.pk and not self._state.adding:
            raise TypeError("敏感审计日志不允许更新。")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("敏感审计日志不允许人工删除。")
