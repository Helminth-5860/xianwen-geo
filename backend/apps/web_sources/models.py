import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class ProtectedQuerySet(models.QuerySet):
    def delete(self):
        raise RuntimeError("Web source evidence cannot be deleted.")


class ImmutableQuerySet(ProtectedQuerySet):
    def update(self, **kwargs):
        raise RuntimeError("Web source evidence cannot be updated.")


class WebSourceImport(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        FETCHING = "fetching", "Fetching"
        RETRY_WAIT = "retry_wait", "Retry wait"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    subject = models.ForeignKey(
        "subjects.Subject", on_delete=models.PROTECT, related_name="web_source_imports"
    )
    canonical_url = models.TextField()
    display_url = models.CharField(max_length=4096)
    has_query = models.BooleanField(default=False)
    hostname_fingerprint = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    version = models.BigIntegerField(default=1)
    idempotency_key_version = models.PositiveSmallIntegerField(default=1)
    idempotency_key_digest = models.CharField(max_length=64, unique=True)
    request_digest = models.CharField(max_length=64)
    generation = models.UUIDField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    retry_count = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    stable_error_code = models.CharField(max_length=64, blank=True)
    request_id = models.UUIDField(null=True, blank=True)
    correlation_id = models.UUIDField(null=True, blank=True)
    latest_parsed_version = models.OneToOneField(
        "WebSourceParsedVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="latest_for_import",
    )
    current_confirmed_version = models.OneToOneField(
        "WebSourceParsedVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="confirmed_for_import",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProtectedQuerySet.as_manager()

    class Meta:
        db_table = "web_source_imports"
        constraints = [
            models.UniqueConstraint(
                fields=("user", "subject", "canonical_url"),
                condition=Q(status__in=("queued", "fetching", "retry_wait")),
                name="web_source_one_open_url",
            ),
            models.CheckConstraint(condition=Q(version__gte=1), name="web_import_version_gte_1"),
            models.CheckConstraint(condition=Q(attempts__gte=0), name="web_import_attempts_gte_0"),
            models.CheckConstraint(
                condition=Q(retry_count__gte=0), name="web_import_retry_count_gte_0"
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status="queued",
                        generation__isnull=True,
                        started_at__isnull=True,
                        finished_at__isnull=True,
                    )
                    | Q(
                        status="fetching",
                        generation__isnull=False,
                        started_at__isnull=False,
                        finished_at__isnull=True,
                    )
                    | Q(
                        status="retry_wait",
                        generation__isnull=False,
                        next_attempt_at__isnull=False,
                        finished_at__isnull=True,
                    )
                    | Q(
                        status__in=("succeeded", "failed"),
                        generation__isnull=False,
                        finished_at__isnull=False,
                    )
                ),
                name="web_import_status_fields",
            ),
        ]
        indexes = [
            models.Index(fields=("status", "next_attempt_at"), name="web_import_retry_idx"),
            models.Index(fields=("user", "subject", "created_at"), name="web_import_owner_idx"),
        ]

    def delete(self, *args, **kwargs):
        raise RuntimeError("Web source imports cannot be deleted.")


class WebSourceSnapshot(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    import_record = models.OneToOneField(
        WebSourceImport, on_delete=models.PROTECT, related_name="snapshot"
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    subject = models.ForeignKey("subjects.Subject", on_delete=models.PROTECT)
    request_url = models.TextField()
    final_url = models.TextField()
    http_status = models.PositiveSmallIntegerField()
    content_type = models.CharField(max_length=64)
    charset = models.CharField(max_length=16)
    actual_bytes = models.PositiveIntegerField()
    response_sha256 = models.CharField(max_length=64)
    redirect_count = models.PositiveSmallIntegerField()
    provenance = models.JSONField(default=dict)
    title = models.CharField(max_length=500, blank=True)
    canonical_text = models.TextField()
    parser_version = models.CharField(max_length=32)
    content_digest = models.CharField(max_length=64)
    fetched_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableQuerySet.as_manager()

    class Meta:
        db_table = "web_source_snapshots"
        constraints = [
            models.CheckConstraint(
                condition=Q(http_status=200), name="web_snapshot_http_status_200"
            ),
            models.CheckConstraint(
                condition=Q(actual_bytes__gt=0), name="web_snapshot_actual_bytes_gt_0"
            ),
            models.CheckConstraint(
                condition=Q(redirect_count__gte=0), name="web_snapshot_redirects_gte_0"
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RuntimeError("Web source snapshots are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("Web source snapshots are immutable.")


class WebSourceParsedVersion(models.Model):  # noqa: DJ008
    class Source(models.TextChoices):
        MACHINE = "machine", "Machine"
        USER_CONFIRMATION = "user_confirmation", "User confirmation"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    import_record = models.ForeignKey(
        WebSourceImport, on_delete=models.PROTECT, related_name="parsed_versions"
    )
    snapshot = models.ForeignKey(
        WebSourceSnapshot, on_delete=models.PROTECT, related_name="parsed_versions"
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    subject = models.ForeignKey("subjects.Subject", on_delete=models.PROTECT)
    version_no = models.PositiveIntegerField()
    source = models.CharField(max_length=24, choices=Source.choices)
    parent_version = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )
    machine_base_version = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="confirmations"
    )
    canonical_text = models.TextField()
    content_digest = models.CharField(max_length=64)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="confirmed_web_source_versions",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableQuerySet.as_manager()

    class Meta:
        db_table = "web_source_parsed_versions"
        constraints = [
            models.UniqueConstraint(
                fields=("import_record", "version_no"), name="web_parsed_version_no_unique"
            ),
            models.UniqueConstraint(
                fields=("parent_version", "content_digest"),
                condition=Q(source="user_confirmation"),
                name="web_confirmation_replay_unique",
            ),
            models.CheckConstraint(
                condition=Q(version_no__gte=1), name="web_parsed_version_no_gte_1"
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        source="machine",
                        version_no=1,
                        parent_version__isnull=True,
                        machine_base_version__isnull=True,
                        confirmed_by__isnull=True,
                        confirmed_at__isnull=True,
                    )
                    | Q(
                        source="user_confirmation",
                        parent_version__isnull=False,
                        machine_base_version__isnull=False,
                        confirmed_by__isnull=False,
                        confirmed_at__isnull=False,
                    )
                ),
                name="web_parsed_version_source_fields",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RuntimeError("Web source parsed versions are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("Web source parsed versions are immutable.")


class WebSourceEvent(models.Model):  # noqa: DJ008
    class EventType(models.TextChoices):
        STARTED = "started", "Started"
        RETRY_SCHEDULED = "retry_scheduled", "Retry scheduled"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CONFIRMED = "confirmed", "Confirmed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    import_record = models.ForeignKey(
        WebSourceImport, on_delete=models.PROTECT, related_name="events"
    )
    snapshot = models.ForeignKey(
        WebSourceSnapshot,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="events",
    )
    parsed_version = models.ForeignKey(
        WebSourceParsedVersion,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="events",
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    subject = models.ForeignKey("subjects.Subject", on_delete=models.PROTECT)
    event_type = models.CharField(max_length=24, choices=EventType.choices)
    stable_error_code = models.CharField(max_length=64, blank=True)
    safe_summary = models.JSONField(default=dict)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="web_source_events",
    )
    request_id = models.UUIDField(null=True, blank=True)
    correlation_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableQuerySet.as_manager()

    class Meta:
        db_table = "web_source_events"
        indexes = [
            models.Index(fields=("import_record", "created_at"), name="web_event_import_idx")
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RuntimeError("Web source events are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("Web source events are append-only.")
