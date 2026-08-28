from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class WebsiteProject(models.Model):  # noqa: DJ008
    class Style(models.TextChoices):
        PROFESSIONAL = "professional", "专业商务"
        TECHNOLOGY = "technology", "科技未来"
        PREMIUM = "premium", "高端品牌"
        INDUSTRIAL = "industrial", "工业制造"
        LOCAL_SERVICE = "local_service", "本地服务"
        AUTHORITY = "authority", "内容权威"

    class Theme(models.TextChoices):
        OCEAN = "ocean", "深海蓝"
        OBSIDIAN = "obsidian", "曜石黑"
        CLOUD = "cloud", "云雾灰"
        AMETHYST = "amethyst", "紫晶"
        JADE = "jade", "翡翠绿"
        GOLD = "gold", "暖金"

    class Density(models.TextChoices):
        COMPACT = "compact", "简洁"
        STANDARD = "standard", "标准"
        RICH = "rich", "丰富"

    class Status(models.TextChoices):
        DRAFT = "draft", "待生成"
        GENERATING = "generating", "正在生成"
        READY = "ready", "已生成"
        FAILED = "failed", "生成未完成"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="website_projects",
    )
    subject = models.OneToOneField(
        "subjects.Subject",
        on_delete=models.PROTECT,
        related_name="website_project",
    )
    subject_version = models.ForeignKey(
        "subjects.SubjectVersion",
        on_delete=models.PROTECT,
        related_name="website_projects",
    )
    style_key = models.CharField(
        max_length=24,
        choices=Style.choices,
        default=Style.PROFESSIONAL,
    )
    theme_key = models.CharField(
        max_length=24,
        choices=Theme.choices,
        default=Theme.OCEAN,
    )
    density_key = models.CharField(
        max_length=24,
        choices=Density.choices,
        default=Density.STANDARD,
    )
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.DRAFT)
    selected_asset_ids = models.JSONField(default=list)
    selected_document_ids = models.JSONField(default=list)
    source_snapshot = models.JSONField(default=dict)
    site_schema_version = models.PositiveSmallIntegerField(default=1)
    site_json = models.JSONField(default=dict)
    generation_count = models.PositiveIntegerField(default=0)
    last_error_code = models.CharField(max_length=100, blank=True)
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "website_projects"
        ordering = ("-updated_at", "-id")
        indexes = [
            models.Index(
                fields=("user", "status", "updated_at"),
                name="website_project_user_idx",
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    style_key__in=(
                        "professional",
                        "technology",
                        "premium",
                        "industrial",
                        "local_service",
                        "authority",
                    )
                ),
                name="website_project_style_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    theme_key__in=("ocean", "obsidian", "cloud", "amethyst", "jade", "gold")
                ),
                name="website_project_theme_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(density_key__in=("compact", "standard", "rich")),
                name="website_project_density_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("draft", "generating", "ready", "failed")),
                name="website_project_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(site_schema_version=1),
                name="website_project_schema_v1",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="website_project_version_gte_1",
            ),
        ]


class WebsiteGenerationJob(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        QUEUED = "queued", "等待生成"
        RUNNING = "running", "正在生成"
        SUCCEEDED = "succeeded", "生成完成"
        FAILED = "failed", "生成未完成"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="website_generation_jobs",
    )
    project = models.ForeignKey(
        WebsiteProject,
        on_delete=models.PROTECT,
        related_name="generation_jobs",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    input_snapshot = models.JSONField(default=dict)
    input_digest = models.CharField(max_length=64)
    provider_key = models.CharField(max_length=100)
    provider_model_id = models.CharField(max_length=255)
    adapter_version = models.CharField(max_length=100)
    prompt_version = models.CharField(max_length=100)
    normalized_usage = models.JSONField(default=dict)
    provider_request_id = models.CharField(max_length=128, blank=True)
    safe_error_code = models.CharField(max_length=100, blank=True)
    idempotency_key_digest = models.CharField(max_length=64, unique=True)
    request_id = models.UUIDField()
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "website_generation_jobs"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(
                fields=("user", "status", "created_at"),
                name="website_job_user_status_idx",
            ),
            models.Index(
                fields=("project", "status", "created_at"),
                name="website_job_project_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=("queued", "running", "succeeded", "failed")),
                name="website_job_status_valid",
            )
        ]
