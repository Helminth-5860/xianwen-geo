import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class ProtectedQuerySet(models.QuerySet):
    def delete(self):
        raise RuntimeError("File evidence cannot be deleted.")


class ImmutableQuerySet(ProtectedQuerySet):
    def update(self, **kwargs):
        raise RuntimeError("Immutable file evidence cannot be updated.")


class FileUploadIntent(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        PENDING_UPLOAD = "pending_upload", "Pending upload"
        VERIFYING = "verifying", "Verifying"
        COMPLETED = "completed", "Completed"
        REJECTED = "rejected", "Rejected"
        EXPIRED = "expired", "Expired"

    class Purpose(models.TextChoices):
        SUBJECT_LIBRARY = "subject_library", "Subject library"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    subject = models.ForeignKey("subjects.Subject", on_delete=models.PROTECT)
    purpose = models.CharField(max_length=32, choices=Purpose.choices)
    declared_filename = models.CharField(max_length=255)
    declared_content_type = models.CharField(max_length=127)
    declared_size = models.BigIntegerField()
    declared_file_kind = models.CharField(max_length=16)
    staging_key = models.CharField(max_length=255, unique=True)
    final_key = models.CharField(max_length=255, unique=True)
    quota_hold_group = models.OneToOneField(
        "quotas.QuotaHoldGroup", on_delete=models.PROTECT, related_name="file_upload_intent"
    )
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PENDING_UPLOAD)
    version = models.BigIntegerField(default=1)
    idempotency_key_version = models.PositiveSmallIntegerField(default=1)
    idempotency_key_digest = models.CharField(max_length=64, unique=True)
    request_digest = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    verification_generation = models.UUIDField(null=True, blank=True)
    retry_count = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    stable_error_code = models.CharField(max_length=64, blank=True)
    staging_cleanup_pending = models.BooleanField(default=False)
    completed_version = models.OneToOneField(
        "DocumentVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="completed_intent",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProtectedQuerySet.as_manager()

    class Meta:
        db_table = "file_upload_intents"
        constraints = [
            models.CheckConstraint(condition=Q(declared_size__gt=0), name="file_intent_size_gt_0"),
            models.CheckConstraint(condition=Q(version__gte=1), name="file_intent_version_gte_1"),
            models.CheckConstraint(
                condition=(
                    Q(status="completed", completed_version__isnull=False)
                    | (~Q(status="completed") & Q(completed_version__isnull=True))
                ),
                name="file_intent_completed_version_state",
            ),
        ]
        indexes = [
            models.Index(fields=("status", "expires_at"), name="file_intent_expiry_idx"),
            models.Index(fields=("status", "next_attempt_at"), name="file_intent_retry_idx"),
            models.Index(fields=("user", "subject", "created_at"), name="file_intent_owner_idx"),
        ]

    def delete(self, *args, **kwargs):
        raise RuntimeError("File record mutation is forbidden.")


class UserDocument(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    subject = models.ForeignKey(
        "subjects.Subject", on_delete=models.PROTECT, related_name="documents"
    )
    purpose = models.CharField(max_length=32, choices=FileUploadIntent.Purpose.choices)
    display_name = models.CharField(max_length=255)
    current_version = models.OneToOneField(
        "DocumentVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="current_for_document",
    )
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ProtectedQuerySet.as_manager()

    class Meta:
        db_table = "user_documents"
        constraints = [
            models.CheckConstraint(condition=Q(version__gte=1), name="document_version_gte_1")
        ]

    def delete(self, *args, **kwargs):
        raise RuntimeError("File record mutation is forbidden.")


class DocumentVersion(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(UserDocument, on_delete=models.PROTECT, related_name="versions")
    version_no = models.PositiveIntegerField()
    object_key = models.CharField(max_length=255, unique=True)
    size_bytes = models.BigIntegerField()
    sha256 = models.CharField(max_length=64)
    detected_file_kind = models.CharField(max_length=16)
    detected_mime = models.CharField(max_length=127)
    security_validation_version = models.PositiveSmallIntegerField(default=1)
    scanner_engine_version = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableQuerySet.as_manager()

    class Meta:
        db_table = "document_versions"
        constraints = [
            models.UniqueConstraint(
                fields=("document", "version_no"), name="document_version_no_unique"
            ),
            models.CheckConstraint(
                condition=Q(version_no__gte=1), name="document_version_no_gte_1"
            ),
            models.CheckConstraint(condition=Q(size_bytes__gt=0), name="document_size_gt_0"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RuntimeError("File record mutation is forbidden.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("File record mutation is forbidden.")


class FileStorageAllocation(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    document_version = models.OneToOneField(
        DocumentVersion, on_delete=models.PROTECT, related_name="storage_allocation"
    )
    quota_account = models.ForeignKey("quotas.QuotaAccount", on_delete=models.PROTECT)
    consume_ledger = models.ForeignKey("quotas.QuotaLedgerEntry", on_delete=models.PROTECT)
    size_bytes = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableQuerySet.as_manager()

    class Meta:
        db_table = "file_storage_allocations"
        constraints = [
            models.CheckConstraint(condition=Q(size_bytes__gt=0), name="file_allocation_size_gt_0")
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RuntimeError("File evidence cannot be deleted.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("File evidence cannot be deleted.")


class SubjectVersionDocumentReference(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subject_version = models.ForeignKey(
        "subjects.SubjectVersion",
        on_delete=models.PROTECT,
        related_name="document_references",
    )
    field_key = models.CharField(max_length=64)
    document_version = models.ForeignKey(
        DocumentVersion,
        on_delete=models.PROTECT,
        related_name="subject_version_references",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableQuerySet.as_manager()

    class Meta:
        db_table = "subject_version_document_references"
        constraints = [
            models.UniqueConstraint(
                fields=("subject_version", "field_key"),
                name="subject_version_document_field_unique",
            )
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RuntimeError("Subject document references are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("Subject document references are immutable.")
