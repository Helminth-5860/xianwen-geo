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
                condition=models.Q(current_mode__in=("confirm", "password")),
                name="risk_policy_valid_mode",
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
    target_type = models.CharField(max_length=50)
    target_id = models.UUIDField()
    request_id = models.UUIDField(db_index=True)
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
