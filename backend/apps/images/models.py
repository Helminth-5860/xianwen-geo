from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class ImmutableImageEvidenceQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError("Image evidence is immutable.")

    def delete(self):
        raise TypeError("Image evidence is immutable.")


class ImageSizePreset(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        DISABLED = "disabled", "Disabled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=100)
    aspect_ratio = models.CharField(max_length=32)
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    provider_params = models.JSONField(default=dict)
    applicable_channels = models.JSONField(default=list)
    applicable_roles = models.JSONField(default=list)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    sort_order = models.PositiveIntegerField(default=0)
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "image_size_presets"
        ordering = ("sort_order", "key", "id")
        constraints = [
            models.CheckConstraint(condition=Q(width__gte=1), name="image_size_width_gte_1"),
            models.CheckConstraint(condition=Q(height__gte=1), name="image_size_height_gte_1"),
            models.CheckConstraint(condition=Q(version__gte=1), name="image_size_version_gte_1"),
        ]


class ImageStylePreset(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        DISABLED = "disabled", "Disabled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    prompt_template = models.TextField()
    applicable_roles = models.JSONField(default=list)
    example_object_key = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    sort_order = models.PositiveIntegerField(default=0)
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "image_style_presets"
        ordering = ("sort_order", "key", "id")
        constraints = [
            models.CheckConstraint(condition=Q(version__gte=1), name="image_style_version_gte_1")
        ]


class ImageGenerationJob(models.Model):  # noqa: DJ008
    class GenerationType(models.TextChoices):
        GENERATE = "generate", "Generate"
        EDIT = "edit", "Reference image edit"

    class Role(models.TextChoices):
        COVER = "cover", "Cover"
        ILLUSTRATION = "illustration", "Illustration"
        CHANNEL = "channel", "Channel"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        RETRY_WAIT = "retry_wait", "Retry wait"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    subject = models.ForeignKey(
        "subjects.Subject", on_delete=models.PROTECT, related_name="image_generation_jobs"
    )
    article = models.ForeignKey(
        "articles.Article",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="image_generation_jobs",
    )
    generation_type = models.CharField(max_length=16, choices=GenerationType.choices)
    role = models.CharField(max_length=24, choices=Role.choices)
    prompt = models.TextField()
    prompt_digest = models.CharField(max_length=64)
    size_preset = models.ForeignKey(ImageSizePreset, on_delete=models.PROTECT)
    size_snapshot = models.JSONField(default=dict)
    style_preset = models.ForeignKey(ImageStylePreset, on_delete=models.PROTECT)
    style_snapshot = models.JSONField(default=dict)
    reference_asset = models.ForeignKey(
        "ImageAsset",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="referenced_by_jobs",
    )
    reference_document_version = models.ForeignKey(
        "documents.DocumentVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="image_generation_jobs",
    )
    reference_url = models.TextField(blank=True)
    reference_snapshot = models.JSONField(default=dict)
    runtime_config = models.ForeignKey("ai.AICapabilityRuntimeConfig", on_delete=models.PROTECT)
    runtime_version = models.PositiveBigIntegerField()
    provider_key = models.CharField(max_length=100)
    provider_model_id = models.CharField(max_length=255)
    api_version = models.CharField(max_length=100)
    adapter_version = models.CharField(max_length=100)
    prompt_version = models.CharField(max_length=100)
    credential_binding_id = models.UUIDField()
    credential_binding_version = models.PositiveBigIntegerField()
    credential_id = models.UUIDField()
    credential_version = models.PositiveIntegerField()
    timeout_seconds = models.PositiveSmallIntegerField()
    retry_base_seconds = models.PositiveIntegerField()
    subscription = models.ForeignKey("plans.Subscription", on_delete=models.PROTECT)
    quota_hold = models.OneToOneField(
        "quotas.QuotaHoldGroup", on_delete=models.PROTECT, related_name="image_generation_job"
    )
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.QUEUED)
    attempt_count = models.PositiveIntegerField(default=0)
    max_retries = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    provider_request_id = models.CharField(max_length=128, blank=True)
    normalized_usage = models.JSONField(default=dict)
    safe_error_code = models.CharField(max_length=100, blank=True)
    idempotency_key_version = models.PositiveSmallIntegerField(default=1)
    idempotency_key_digest = models.CharField(max_length=64, unique=True)
    request_digest = models.CharField(max_length=64)
    request_id = models.UUIDField()
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "image_generation_jobs"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(
                fields=("user", "status", "created_at"), name="image_job_owner_status_idx"
            ),
            models.Index(fields=("status", "next_attempt_at"), name="image_job_retry_idx"),
        ]


class ImageAsset(models.Model):  # noqa: DJ008
    class SourceType(models.TextChoices):
        GENERATED = "generated", "Generated"
        UPLOADED = "uploaded", "Uploaded"
        DERIVATIVE = "derivative", "Derivative"

    class ModerationStatus(models.TextChoices):
        APPROVED = "approved", "Approved"
        SUSPECTED = "suspected", "Suspected"
        REJECTED = "rejected", "Rejected"
        SERVICE_ERROR = "service_error", "Service error"

    class LifecycleStatus(models.TextChoices):
        ACTIVE = "active", "Active"
        TRASHED = "trashed", "Trashed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    subject = models.ForeignKey(
        "subjects.Subject", on_delete=models.PROTECT, related_name="image_assets"
    )
    article = models.ForeignKey(
        "articles.Article",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="image_assets",
    )
    generation_job = models.OneToOneField(
        ImageGenerationJob,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="result_asset",
    )
    source_image = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="derived_assets"
    )
    source_type = models.CharField(max_length=16, choices=SourceType.choices)
    role = models.CharField(max_length=24, choices=ImageGenerationJob.Role.choices)
    object_key = models.CharField(max_length=500, unique=True)
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    mime_type = models.CharField(max_length=64)
    size_bytes = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    provider_key = models.CharField(max_length=100, blank=True)
    provider_model_id = models.CharField(max_length=255, blank=True)
    generation_capability = models.CharField(max_length=64, blank=True)
    adapter_version = models.CharField(max_length=100, blank=True)
    prompt_digest = models.CharField(max_length=64, blank=True)
    source_provenance = models.JSONField(default=dict)
    moderation_status = models.CharField(max_length=24, choices=ModerationStatus.choices)
    is_subject_library = models.BooleanField(default=False)
    lifecycle_status = models.CharField(
        max_length=16, choices=LifecycleStatus.choices, default=LifecycleStatus.ACTIVE
    )
    deleted_at = models.DateTimeField(null=True, blank=True)
    generated_at = models.DateTimeField(null=True, blank=True)
    available_at = models.DateTimeField()
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "images"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(
                fields=("user", "subject", "lifecycle_status", "created_at"),
                name="image_asset_owner_idx",
            )
        ]
        constraints = [
            models.CheckConstraint(condition=Q(width__gte=1), name="image_asset_width_gte_1"),
            models.CheckConstraint(condition=Q(height__gte=1), name="image_asset_height_gte_1"),
            models.CheckConstraint(
                condition=Q(size_bytes__gte=1), name="image_asset_size_bytes_gte_1"
            ),
            models.CheckConstraint(condition=Q(version__gte=1), name="image_asset_version_gte_1"),
            models.CheckConstraint(
                condition=(
                    Q(lifecycle_status="active", deleted_at__isnull=True)
                    | Q(lifecycle_status="trashed", deleted_at__isnull=False)
                ),
                name="image_asset_lifecycle_shape",
            ),
        ]


class ImageReferenceLink(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(
        ImageGenerationJob, on_delete=models.PROTECT, related_name="reference_links"
    )
    image = models.ForeignKey(ImageAsset, on_delete=models.PROTECT)
    purpose = models.CharField(max_length=32, default="reference")
    snapshot_digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableImageEvidenceQuerySet.as_manager()

    class Meta:
        db_table = "image_reference_links"
        constraints = [
            models.UniqueConstraint(
                fields=("job", "image", "purpose"), name="image_reference_link_unique"
            )
        ]


class ImageGenerationResult(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.OneToOneField(
        ImageGenerationJob, on_delete=models.PROTECT, related_name="normalized_result"
    )
    image = models.OneToOneField(
        ImageAsset, on_delete=models.PROTECT, related_name="generation_result"
    )
    provider_model_id = models.CharField(max_length=255)
    provider_created = models.BigIntegerField(null=True, blank=True)
    provider_size = models.CharField(max_length=64, blank=True)
    output_digest = models.CharField(max_length=64)
    safe_metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableImageEvidenceQuerySet.as_manager()

    class Meta:
        db_table = "image_generation_results"


class ImageModerationReview(models.Model):  # noqa: DJ008
    class Source(models.TextChoices):
        PROVIDER = "provider", "Provider"
        SYSTEM = "system", "System"
        MANUAL = "manual", "Manual"

    class Decision(models.TextChoices):
        APPROVED = "approved", "Approved"
        SUSPECTED = "suspected", "Suspected"
        REJECTED = "rejected", "Rejected"
        SERVICE_ERROR = "service_error", "Service error"
        APPEAL_REQUESTED = "appeal_requested", "Appeal requested"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(
        ImageGenerationJob, on_delete=models.PROTECT, related_name="moderation_reviews"
    )
    image = models.ForeignKey(
        ImageAsset,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="moderation_reviews",
    )
    source = models.CharField(max_length=16, choices=Source.choices)
    decision = models.CharField(max_length=24, choices=Decision.choices)
    risk_categories = models.JSONField(default=list)
    responsibility = models.CharField(max_length=32)
    quota_released = models.BooleanField(default=False)
    appeal_no = models.PositiveSmallIntegerField(default=0)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT
    )
    note = models.CharField(max_length=1000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableImageEvidenceQuerySet.as_manager()

    class Meta:
        db_table = "image_moderation_reviews"
        constraints = [
            models.UniqueConstraint(
                fields=("image", "appeal_no"),
                condition=Q(image__isnull=False, appeal_no__gt=0),
                name="image_moderation_one_appeal_no",
            )
        ]


class ImageDerivative(models.Model):  # noqa: DJ008
    class Kind(models.TextChoices):
        COMPRESSED = "compressed", "Compressed"
        CROP = "crop", "Crop"
        CHANNEL = "channel", "Channel"
        FORMAT = "format", "Format"
        AI_EDIT = "ai_edit", "AI reference edit"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_image = models.ForeignKey(
        ImageAsset, on_delete=models.PROTECT, related_name="derivatives"
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    object_key = models.CharField(max_length=500, unique=True)
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    mime_type = models.CharField(max_length=64)
    size_bytes = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    ai_used = models.BooleanField(default=False)
    parameters = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableImageEvidenceQuerySet.as_manager()

    class Meta:
        db_table = "image_derivatives"


class ImageBatchDownload(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    subject = models.ForeignKey("subjects.Subject", on_delete=models.PROTECT)
    object_key = models.CharField(max_length=500, unique=True)
    image_count = models.PositiveIntegerField()
    content_digest = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableImageEvidenceQuerySet.as_manager()

    class Meta:
        db_table = "image_batch_downloads"
