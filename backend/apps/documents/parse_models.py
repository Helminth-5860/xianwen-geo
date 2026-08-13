import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from .models import (
    DocumentVersion,
    ImmutableQuerySet,
    ProtectedQuerySet,
    UserDocument,
)


class DocumentParseJob(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        RETRY_WAIT = "retry_wait", "Retry wait"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    subject = models.ForeignKey("subjects.Subject", on_delete=models.PROTECT)
    document = models.ForeignKey(UserDocument, on_delete=models.PROTECT)
    document_version = models.OneToOneField(
        DocumentVersion, on_delete=models.PROTECT, related_name="parse_job"
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    parser_key = models.CharField(max_length=32)
    parser_version = models.CharField(max_length=32)
    ocr_provider_key = models.CharField(max_length=32, blank=True)
    idempotency_key_version = models.PositiveSmallIntegerField(default=1)
    idempotency_key_digest = models.CharField(max_length=64, unique=True)
    request_digest = models.CharField(max_length=64)
    generation = models.UUIDField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    retry_count = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    stable_error_code = models.CharField(max_length=64, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    request_id = models.UUIDField(null=True, blank=True)
    correlation_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProtectedQuerySet.as_manager()

    class Meta:
        db_table = "document_parse_jobs"
        constraints = [
            models.CheckConstraint(condition=Q(attempts__gte=0), name="parse_job_attempts_gte_0"),
            models.CheckConstraint(
                condition=Q(retry_count__gte=0), name="parse_job_retry_count_gte_0"
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="queued", generation__isnull=True, finished_at__isnull=True)
                    | Q(
                        status="running",
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
                name="parse_job_status_fields",
            ),
        ]
        indexes = [
            models.Index(fields=("status", "next_attempt_at"), name="parse_job_retry_idx"),
            models.Index(fields=("user", "subject", "created_at"), name="parse_job_owner_idx"),
        ]

    def delete(self, *args, **kwargs):
        raise RuntimeError("Parse jobs cannot be deleted.")


class DocumentParsedVersion(models.Model):  # noqa: DJ008
    class Source(models.TextChoices):
        PARSER = "parser", "Parser"
        USER_CONFIRMATION = "user_confirmation", "User confirmation"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    subject = models.ForeignKey("subjects.Subject", on_delete=models.PROTECT)
    document = models.ForeignKey(UserDocument, on_delete=models.PROTECT)
    document_version = models.ForeignKey(
        DocumentVersion, on_delete=models.PROTECT, related_name="parsed_versions"
    )
    version_no = models.PositiveIntegerField()
    source = models.CharField(max_length=24, choices=Source.choices)
    parent_version = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )
    machine_base_version = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="confirmations"
    )
    extracted_text = models.TextField()
    tables_json = models.JSONField(default=list)
    warning_codes = models.JSONField(default=list)
    parser_key = models.CharField(max_length=32)
    parser_version = models.CharField(max_length=32)
    ocr_provider_key = models.CharField(max_length=32, blank=True)
    ocr_engine_version = models.CharField(max_length=64, blank=True)
    content_digest = models.CharField(max_length=64)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="confirmed_document_parse_versions",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableQuerySet.as_manager()

    class Meta:
        db_table = "document_parsed_versions"
        constraints = [
            models.UniqueConstraint(
                fields=("document_version", "version_no"), name="parsed_version_no_unique"
            ),
            models.UniqueConstraint(
                fields=("parent_version", "content_digest"),
                condition=Q(source="user_confirmation"),
                name="parsed_confirmation_replay_unique",
            ),
            models.CheckConstraint(condition=Q(version_no__gte=1), name="parsed_version_no_gte_1"),
            models.CheckConstraint(
                condition=(
                    Q(
                        source="parser",
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
                name="parsed_version_source_fields",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RuntimeError("Parsed versions are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("Parsed versions are immutable.")


class DocumentParseState(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    subject = models.ForeignKey("subjects.Subject", on_delete=models.PROTECT)
    document = models.ForeignKey(UserDocument, on_delete=models.PROTECT)
    document_version = models.OneToOneField(
        DocumentVersion, on_delete=models.PROTECT, related_name="parse_state"
    )
    latest_parsed_version = models.OneToOneField(
        DocumentParsedVersion,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="latest_for_state",
    )
    current_confirmed_version = models.OneToOneField(
        DocumentParsedVersion,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="confirmed_for_state",
    )
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProtectedQuerySet.as_manager()

    class Meta:
        db_table = "document_parse_states"
        constraints = [
            models.CheckConstraint(condition=Q(version__gte=1), name="parse_state_version_gte_1")
        ]

    def delete(self, *args, **kwargs):
        raise RuntimeError("Parse state cannot be deleted.")


class DocumentParseEvent(models.Model):  # noqa: DJ008
    class EventType(models.TextChoices):
        STARTED = "started", "Started"
        RETRY_SCHEDULED = "retry_scheduled", "Retry scheduled"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CONFIRMED = "confirmed", "Confirmed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    subject = models.ForeignKey("subjects.Subject", on_delete=models.PROTECT)
    document = models.ForeignKey(UserDocument, on_delete=models.PROTECT)
    document_version = models.ForeignKey(DocumentVersion, on_delete=models.PROTECT)
    job = models.ForeignKey(
        DocumentParseJob, null=True, blank=True, on_delete=models.PROTECT, related_name="events"
    )
    parsed_version = models.ForeignKey(
        DocumentParsedVersion,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="events",
    )
    event_type = models.CharField(max_length=24, choices=EventType.choices)
    stable_error_code = models.CharField(max_length=64, blank=True)
    safe_summary = models.JSONField(default=dict)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="document_parse_events",
    )
    request_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableQuerySet.as_manager()

    class Meta:
        db_table = "document_parse_events"
        indexes = [
            models.Index(fields=("document_version", "created_at"), name="parse_event_doc_idx")
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RuntimeError("Parse events are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("Parse events are append-only.")
