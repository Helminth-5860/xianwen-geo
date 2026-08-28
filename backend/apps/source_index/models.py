from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class ProtectedSourceScanQuerySet(models.QuerySet):
    def delete(self):
        raise TypeError("Source index scan history cannot be deleted.")


class SourceIndexScan(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        PARTIAL = "partial", "Partial"
        LIMIT_REACHED = "limit_reached", "Limit reached"
        FAILED = "failed", "Failed"

    class Stage(models.TextChoices):
        PREPARING = "preparing", "Preparing"
        SEARCHING = "searching", "Searching"
        CLASSIFYING = "classifying", "Classifying"
        SCORING = "scoring", "Scoring"
        COMPLETED = "completed", "Completed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="source_index_scans",
    )
    subject = models.ForeignKey(
        "subjects.Subject",
        on_delete=models.PROTECT,
        related_name="source_index_scans",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    stage = models.CharField(max_length=20, choices=Stage.choices, default=Stage.PREPARING)
    provider = models.CharField(max_length=32, default="baidu")
    query_count = models.PositiveIntegerField(default=0)
    provider_request_count = models.PositiveIntegerField(default=0)
    provider_error_count = models.PositiveIntegerField(default=0)
    raw_result_count = models.PositiveIntegerField(default=0)
    unique_result_count = models.PositiveIntegerField(default=0)
    public_source_count = models.PositiveIntegerField(default=0)
    independent_domain_count = models.PositiveIntegerField(default=0)
    news_media_count = models.PositiveIntegerField(default=0)
    high_weight_count = models.PositiveIntegerField(default=0)
    recent_30d_count = models.PositiveIntegerField(default=0)
    index_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    factor_scores = models.JSONField(default=dict)
    progress = models.JSONField(default=dict)
    formula_version = models.CharField(max_length=64, default="source-index-v1")
    stable_error_code = models.CharField(max_length=100, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    elapsed_ms = models.PositiveBigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProtectedSourceScanQuerySet.as_manager()

    class Meta:
        db_table = "source_index_scans"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("user", "subject", "created_at"), name="src_scan_user_subj_idx"),
            models.Index(fields=("status", "created_at"), name="src_scan_status_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    status__in=(
                        "queued",
                        "running",
                        "succeeded",
                        "partial",
                        "limit_reached",
                        "failed",
                    )
                ),
                name="src_scan_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(
                    stage__in=(
                        "preparing",
                        "searching",
                        "classifying",
                        "scoring",
                        "completed",
                    )
                ),
                name="src_scan_stage_valid",
            ),
            models.CheckConstraint(
                condition=Q(index_score__isnull=True) | Q(index_score__gte=0, index_score__lte=100),
                name="src_scan_index_range",
            ),
            models.UniqueConstraint(
                fields=("user", "subject"),
                condition=Q(status__in=("queued", "running")),
                name="src_scan_one_active_per_subject",
            ),
        ]

    def delete(self, *args, **kwargs):
        raise TypeError("Source index scan history cannot be deleted.")


class SourceIndexItem(models.Model):  # noqa: DJ008
    class SourceType(models.TextChoices):
        GOVERNMENT_ASSOCIATION = "government_association", "政府/协会"
        NEWS_MEDIA = "news_media", "新闻媒体"
        INDUSTRY_MEDIA = "industry_media", "行业媒体"
        ENTERPRISE_SITE = "enterprise_site", "企业网站"
        CONTENT_PLATFORM = "content_platform", "内容平台/自媒体"
        DIRECTORY_BUSINESS = "directory_business", "黄页/工商"
        FORUM_COMMUNITY = "forum_community", "论坛社区"
        OTHER = "other", "其他"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scan = models.ForeignKey(SourceIndexScan, on_delete=models.CASCADE, related_name="items")
    original_url = models.URLField(max_length=4096)
    normalized_url = models.CharField(max_length=4096)
    domain = models.CharField(max_length=255)
    root_domain = models.CharField(max_length=255)
    website = models.CharField(max_length=500, blank=True)
    title = models.CharField(max_length=1000)
    snippet = models.TextField(blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    source_type = models.CharField(max_length=32, choices=SourceType.choices)
    authority_score = models.PositiveSmallIntegerField()
    relevance_score = models.PositiveSmallIntegerField()
    visibility_score = models.PositiveSmallIntegerField()
    freshness_score = models.PositiveSmallIntegerField()
    source_weight = models.DecimalField(max_digits=5, decimal_places=2)
    best_rank = models.PositiveIntegerField()
    matched_query_count = models.PositiveIntegerField(default=1)
    repost_cluster_id = models.CharField(max_length=64, blank=True)
    score_version = models.CharField(max_length=64, default="source-weight-v1")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "source_index_items"
        ordering = ("-source_weight", "best_rank", "id")
        indexes = [
            models.Index(
                fields=("scan", "source_type", "source_weight"),
                name="src_item_type_score_idx",
            ),
            models.Index(fields=("scan", "root_domain"), name="src_item_domain_idx"),
            models.Index(fields=("scan", "published_at"), name="src_item_date_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("scan", "normalized_url"),
                name="src_item_scan_url_unique",
            ),
            models.CheckConstraint(
                condition=Q(authority_score__lte=100),
                name="src_item_authority_lte100",
            ),
            models.CheckConstraint(
                condition=Q(relevance_score__lte=100),
                name="src_item_relevance_lte100",
            ),
            models.CheckConstraint(
                condition=Q(visibility_score__lte=100),
                name="src_item_visibility_lte100",
            ),
            models.CheckConstraint(
                condition=Q(freshness_score__lte=100),
                name="src_item_freshness_lte100",
            ),
            models.CheckConstraint(
                condition=Q(source_weight__gte=0, source_weight__lte=100),
                name="src_item_weight_range",
            ),
        ]


class SourceIndexHit(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scan = models.ForeignKey(SourceIndexScan, on_delete=models.CASCADE, related_name="hits")
    item = models.ForeignKey(SourceIndexItem, on_delete=models.CASCADE, related_name="hits")
    query = models.CharField(max_length=200)
    rank = models.PositiveIntegerField()
    range_start = models.DateField(null=True, blank=True)
    range_end = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "source_index_hits"
        ordering = ("scan_id", "query", "rank", "id")
        indexes = [
            models.Index(fields=("scan", "query", "rank"), name="src_hit_query_rank_idx"),
            models.Index(fields=("item", "rank"), name="src_hit_item_rank_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("scan", "item", "query", "range_start", "range_end"),
                name="src_hit_scan_item_query_range_unique",
                nulls_distinct=False,
            )
        ]
