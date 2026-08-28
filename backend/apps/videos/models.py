from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class VideoGenerationJob(models.Model):  # noqa: DJ008
    class GenerationMode(models.TextChoices):
        TEXT = "text", "文字生成"
        IMAGE = "image", "图片生成"

    class AspectRatio(models.TextChoices):
        PORTRAIT = "9:16", "竖屏 9:16"
        LANDSCAPE = "16:9", "横屏 16:9"

    class Status(models.TextChoices):
        QUEUED = "queued", "排队中"
        PROCESSING = "processing", "生成中"
        SUCCEEDED = "succeeded", "已完成"
        FAILED = "failed", "生成失败"

    class Stage(models.TextChoices):
        FIRST_FRAME = "first_frame", "准备首帧"
        SUBMIT = "submit", "准备提交"
        SUBMITTING = "submitting", "正在提交"
        POLL = "poll", "等待生成"
        TRANSFER = "transfer", "保存视频"
        COMPLETE = "complete", "已完成"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="video_generation_jobs"
    )
    tenant = models.ForeignKey(
        "users.Tenant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="video_generation_jobs",
    )
    subject = models.ForeignKey(
        "subjects.Subject", on_delete=models.PROTECT, related_name="video_generation_jobs"
    )
    generation_mode = models.CharField(max_length=16, choices=GenerationMode.choices)
    prompt = models.TextField()
    prompt_digest = models.CharField(max_length=64)
    source_document_version = models.ForeignKey(
        "documents.DocumentVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="video_generation_jobs",
    )
    first_frame = models.ForeignKey(
        "images.ImageAsset",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="video_generation_jobs",
    )
    aspect_ratio = models.CharField(max_length=8, choices=AspectRatio.choices)
    duration_seconds = models.PositiveSmallIntegerField()
    resolution = models.CharField(max_length=16, default="720P")
    provider_key = models.CharField(max_length=64, default="aliyun")
    provider_model_id = models.CharField(max_length=255, default="wan2.6-i2v-flash")
    provider_job_id = models.CharField(max_length=128, blank=True)
    provider_request_id = models.CharField(max_length=128, blank=True)
    subscription = models.ForeignKey(
        "plans.Subscription", on_delete=models.PROTECT, related_name="video_generation_jobs"
    )
    quota_hold = models.OneToOneField(
        "quotas.QuotaHoldGroup", on_delete=models.PROTECT, related_name="video_generation_job"
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    stage = models.CharField(max_length=24, choices=Stage.choices, default=Stage.FIRST_FRAME)
    safe_error_code = models.CharField(max_length=100, blank=True)
    safe_error_message = models.CharField(max_length=200, blank=True)
    poll_count = models.PositiveIntegerField(default=0)
    attempt_count = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    lease_generation = models.UUIDField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    idempotency_key_version = models.PositiveSmallIntegerField(default=1)
    idempotency_key_digest = models.CharField(max_length=64, unique=True)
    request_digest = models.CharField(max_length=64)
    request_id = models.UUIDField(db_index=True)
    version = models.PositiveBigIntegerField(default=1)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "video_generation_jobs"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("user", "subject", "created_at"), name="video_job_owner_idx"),
            models.Index(
                fields=("status", "next_attempt_at", "lease_expires_at"),
                name="video_job_due_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("provider_key", "provider_job_id"),
                condition=~Q(provider_job_id=""),
                name="video_provider_job_unique",
            ),
            models.CheckConstraint(
                condition=Q(generation_mode="text", source_document_version__isnull=True)
                | Q(generation_mode="image", source_document_version__isnull=False),
                name="video_job_source_shape",
            ),
            models.CheckConstraint(
                condition=Q(aspect_ratio__in=("9:16", "16:9")),
                name="video_job_aspect_valid",
            ),
            models.CheckConstraint(
                condition=Q(duration_seconds__in=(5, 10)), name="video_job_duration_valid"
            ),
            models.CheckConstraint(
                condition=Q(resolution="720P"), name="video_job_resolution_720p"
            ),
            models.CheckConstraint(condition=Q(version__gte=1), name="video_job_version_gte_1"),
        ]


class VideoAsset(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="video_assets"
    )
    tenant = models.ForeignKey(
        "users.Tenant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="video_assets",
    )
    subject = models.ForeignKey(
        "subjects.Subject", on_delete=models.PROTECT, related_name="video_assets"
    )
    generation_job = models.OneToOneField(
        VideoGenerationJob, on_delete=models.PROTECT, related_name="result_asset"
    )
    object_key = models.CharField(max_length=500, unique=True)
    duration_seconds = models.PositiveSmallIntegerField()
    aspect_ratio = models.CharField(max_length=8, choices=VideoGenerationJob.AspectRatio.choices)
    resolution = models.CharField(max_length=16, default="720P")
    mime_type = models.CharField(max_length=64, default="video/mp4")
    size_bytes = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    is_subject_library = models.BooleanField(default=False)
    available_at = models.DateTimeField()
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "videos"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(
                fields=("user", "subject", "is_subject_library", "created_at"),
                name="video_asset_owner_idx",
            )
        ]
        constraints = [
            models.CheckConstraint(condition=Q(size_bytes__gte=1), name="video_asset_size_gte_1"),
            models.CheckConstraint(
                condition=Q(duration_seconds__in=(5, 10)), name="video_asset_duration_valid"
            ),
            models.CheckConstraint(
                condition=Q(aspect_ratio__in=("9:16", "16:9")),
                name="video_asset_aspect_valid",
            ),
            models.CheckConstraint(
                condition=Q(resolution="720P"), name="video_asset_resolution_720p"
            ),
            models.CheckConstraint(condition=Q(version__gte=1), name="video_asset_version_gte_1"),
        ]
