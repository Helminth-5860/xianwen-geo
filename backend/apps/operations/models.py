import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError("Operational evidence is append-only.")

    def delete(self):
        raise TypeError("Operational evidence is append-only.")


class CustomerStatus(models.Model):  # noqa: DJ008
    class State(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=500, blank=True)
    state = models.CharField(max_length=16, choices=State.choices, default=State.ACTIVE)
    is_builtin = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=100)
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "customer_statuses"
        ordering = ("sort_order", "name", "id")
        constraints = [
            models.CheckConstraint(condition=Q(version__gte=1), name="customer_status_ver_gte_1")
        ]

    def delete(self, *args, **kwargs):
        raise TypeError("Customer statuses can only be disabled.")


class CustomerProfile(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="customer_profile"
    )
    status = models.ForeignKey(
        CustomerStatus, null=True, blank=True, on_delete=models.PROTECT, related_name="profiles"
    )
    source = models.CharField(max_length=100, blank=True)
    internal_note = models.CharField(max_length=2000, blank=True)
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "customer_profiles"
        constraints = [
            models.CheckConstraint(condition=Q(version__gte=1), name="customer_profile_ver_gte_1")
        ]


class CustomerTag(models.Model):  # noqa: DJ008
    class State(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=100)
    state = models.CharField(max_length=16, choices=State.choices, default=State.ACTIVE)
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "customer_tags"
        ordering = ("name", "id")
        constraints = [
            models.CheckConstraint(condition=Q(version__gte=1), name="customer_tag_ver_gte_1")
        ]

    def delete(self, *args, **kwargs):
        raise TypeError("Customer tags can only be disabled.")


class CustomerTagLink(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="customer_tag_links"
    )
    tag = models.ForeignKey(CustomerTag, on_delete=models.PROTECT, related_name="customer_links")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_customer_tags"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "customer_tag_links"
        constraints = [
            models.UniqueConstraint(fields=("customer", "tag"), name="customer_tag_link_unique")
        ]


class CustomerContactLog(models.Model):  # noqa: DJ008
    class Method(models.TextChoices):
        PHONE = "phone", "Phone"
        SMS = "sms", "SMS"
        WECHAT = "wechat", "WeChat"
        EMAIL = "email", "Email"
        OTHER = "other", "Other"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="customer_contact_logs"
    )
    actor = models.ForeignKey(
        "admin_rbac.AdminProfile", on_delete=models.PROTECT, related_name="customer_contact_logs"
    )
    contacted_at = models.DateTimeField()
    method = models.CharField(max_length=16, choices=Method.choices)
    content = models.CharField(max_length=4000)
    next_followup_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        db_table = "customer_contact_logs"
        ordering = ("-contacted_at", "-id")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Customer contact evidence is append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Customer contact evidence is append-only.")


class CustomerFollowup(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="customer_followups"
    )
    assignee = models.ForeignKey(
        "admin_rbac.AdminProfile", on_delete=models.PROTECT, related_name="customer_followups"
    )
    source_contact = models.ForeignKey(
        CustomerContactLog, null=True, blank=True, on_delete=models.PROTECT
    )
    due_at = models.DateTimeField()
    note = models.CharField(max_length=2000)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    completed_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "customer_followups"
        ordering = ("status", "due_at", "id")
        constraints = [
            models.CheckConstraint(condition=Q(version__gte=1), name="customer_followup_ver_gte_1"),
            models.CheckConstraint(
                condition=(
                    Q(status="completed", completed_at__isnull=False)
                    | Q(status__in=("open", "cancelled"), completed_at__isnull=True)
                ),
                name="customer_followup_completion_shape",
            ),
        ]


class Announcement(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        DISABLED = "disabled", "Disabled"

    class Audience(models.TextChoices):
        ALL = "all", "All"
        PLAN = "plan", "Plan"
        USER = "user", "User"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=200)
    body = models.TextField(max_length=20_000)
    audience = models.CharField(max_length=16, choices=Audience.choices, default=Audience.ALL)
    audience_keys = models.JSONField(default=list)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    pinned = models.BooleanField(default=False)
    version = models.PositiveBigIntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_announcements"
    )
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "announcements"
        ordering = ("-pinned", "-published_at", "-created_at")
        constraints = [
            models.CheckConstraint(condition=Q(version__gte=1), name="announcement_ver_gte_1")
        ]


class UserFeedback(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        REPLIED = "replied", "Replied"
        CLOSED = "closed", "Closed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="feedback_entries"
    )
    subject = models.ForeignKey("subjects.Subject", null=True, blank=True, on_delete=models.PROTECT)
    module = models.CharField(max_length=64)
    description = models.TextField(max_length=10_000)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    admin_reply = models.TextField(max_length=10_000, blank=True)
    replied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="replied_feedback_entries",
    )
    replied_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "user_feedback"
        ordering = ("-created_at", "-id")
        constraints = [
            models.CheckConstraint(condition=Q(version__gte=1), name="user_feedback_ver_gte_1")
        ]


class SupportViewRequest(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACTIVE = "active", "Active"
        REVOKED = "revoked", "Revoked"
        EXPIRED = "expired", "Expired"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    requester = models.ForeignKey(
        "admin_rbac.AdminProfile", on_delete=models.PROTECT, related_name="support_view_requests"
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="support_view_requests"
    )
    reason = models.CharField(max_length=1000)
    forced = models.BooleanField(default=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    expires_at = models.DateTimeField()
    authorized_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "support_view_requests"
        ordering = ("-created_at", "-id")
        constraints = [
            models.CheckConstraint(condition=Q(version__gte=1), name="support_view_ver_gte_1")
        ]


class SupportViewAuditLog(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    support_request = models.ForeignKey(
        SupportViewRequest, on_delete=models.PROTECT, related_name="access_logs"
    )
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    page_key = models.CharField(max_length=100)
    outcome = models.CharField(max_length=32)
    request_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        db_table = "support_view_audit_logs"
        ordering = ("-created_at", "-id")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Support-view audit evidence is append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Support-view audit evidence is append-only.")


class SystemAlert(models.Model):  # noqa: DJ008
    class Severity(models.TextChoices):
        INFO = "info", "Info"
        IMPORTANT = "important", "Important"
        CRITICAL = "critical", "Critical"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"
        RESOLVED = "resolved", "Resolved"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fingerprint = models.CharField(max_length=64, unique=True)
    category = models.CharField(max_length=100)
    severity = models.CharField(max_length=16, choices=Severity.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    occurrences = models.PositiveBigIntegerField(default=1)
    safe_summary = models.JSONField(default=dict)
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT
    )
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "system_alerts"
        ordering = ("status", "-last_seen_at", "-id")


class BackupRecord(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        RUNNING = "running", "Running"
        VERIFIED = "verified", "Verified"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=32)
    scope = models.CharField(max_length=100)
    location_reference = models.CharField(max_length=500)
    encrypted = models.BooleanField(default=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PLANNED)
    checksum_sha256 = models.CharField(max_length=64, blank=True)
    restore_verified_at = models.DateTimeField(null=True, blank=True)
    safe_error_code = models.CharField(max_length=100, blank=True)
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "backup_records"
        ordering = ("-created_at", "-id")


class RetentionJob(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=64)
    scope = models.CharField(max_length=100)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    safe_summary = models.JSONField(default=dict)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "retention_jobs"
        ordering = ("-created_at", "-id")


class ReleaseEvidence(models.Model):  # noqa: DJ008
    """Append-only metadata produced by a real external deployment/UAT gate."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    environment = models.CharField(max_length=32)
    evidence_key = models.CharField(max_length=100)
    deploy_sha = models.CharField(max_length=40)
    safe_summary = models.JSONField(default=dict)
    observed_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        db_table = "release_evidence"
        ordering = ("-observed_at", "-id")
        indexes = [
            models.Index(
                fields=("environment", "evidence_key", "deploy_sha", "expires_at"),
                name="release_evidence_lookup_idx",
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(expires_at__gt=models.F("observed_at")),
                name="release_evidence_expiry_after_observed",
            )
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Release evidence is append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Release evidence is append-only.")
