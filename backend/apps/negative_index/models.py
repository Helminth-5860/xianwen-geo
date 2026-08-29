from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class ProtectedNegativeScanQuerySet(models.QuerySet):
    def delete(self):
        raise TypeError("Negative index scan history cannot be deleted.")


class NegativeIndexScan(models.Model):  # noqa: DJ008
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
        VERIFYING = "verifying", "Verifying"
        CLUSTERING = "clustering", "Clustering"
        SCORING = "scoring", "Scoring"
        COMPLETED = "completed", "Completed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="negative_index_scans",
    )
    subject = models.ForeignKey(
        "subjects.Subject",
        on_delete=models.PROTECT,
        related_name="negative_index_scans",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.QUEUED,
    )
    stage = models.CharField(
        max_length=20,
        choices=Stage.choices,
        default=Stage.PREPARING,
    )
    provider = models.CharField(max_length=32, default="baidu")
    ai_provider = models.CharField(max_length=32, blank=True)
    ai_model_key = models.CharField(max_length=100, blank=True)
    ai_provider_model_id = models.CharField(max_length=255, blank=True)
    query_count = models.PositiveIntegerField(default=0)
    provider_request_count = models.PositiveIntegerField(default=0)
    provider_error_count = models.PositiveIntegerField(default=0)
    raw_result_count = models.PositiveIntegerField(default=0)
    unique_result_count = models.PositiveIntegerField(default=0)
    candidate_count = models.PositiveIntegerField(default=0)
    negative_item_count = models.PositiveIntegerField(default=0)
    event_count = models.PositiveIntegerField(default=0)
    high_risk_event_count = models.PositiveIntegerField(default=0)
    recent_30d_event_count = models.PositiveIntegerField(default=0)
    verified_item_count = models.PositiveIntegerField(default=0)
    index_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )
    factor_scores = models.JSONField(default=dict)
    progress = models.JSONField(default=dict)
    formula_version = models.CharField(max_length=64, default="negative-index-v1")
    classifier_version = models.CharField(
        max_length=64,
        default="negative-classifier-v1",
    )
    stable_error_code = models.CharField(max_length=100, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    elapsed_ms = models.PositiveBigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProtectedNegativeScanQuerySet.as_manager()

    class Meta:
        db_table = "negative_index_scans"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(
                fields=("user", "subject", "created_at"),
                name="neg_scan_user_subj_idx",
            ),
            models.Index(
                fields=("status", "created_at"),
                name="neg_scan_status_idx",
            ),
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
                name="neg_scan_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(
                    stage__in=(
                        "preparing",
                        "searching",
                        "classifying",
                        "verifying",
                        "clustering",
                        "scoring",
                        "completed",
                    )
                ),
                name="neg_scan_stage_valid",
            ),
            models.CheckConstraint(
                condition=Q(index_score__isnull=True)
                | Q(index_score__gte=0, index_score__lte=100),
                name="neg_scan_index_range",
            ),
            models.UniqueConstraint(
                fields=("user", "subject"),
                condition=Q(status__in=("queued", "running")),
                name="neg_scan_one_active_per_subject",
            ),
        ]

    def delete(self, *args, **kwargs):
        raise TypeError("Negative index scan history cannot be deleted.")


class NegativeEvent(models.Model):  # noqa: DJ008
    class Category(models.TextChoices):
        REGULATORY = "regulatory", "监管处罚"
        JUDICIAL = "judicial", "司法风险"
        CONSUMER_COMPLAINT = "consumer_complaint", "消费者投诉"
        PRODUCT_SERVICE_INCIDENT = "product_service_incident", "产品/服务事故"
        BUSINESS_OPERATION = "business_operation", "经营风险"
        MEDIA_NEGATIVE = "media_negative", "媒体负面"
        ONLINE_OPINION = "online_opinion", "网络舆情"
        OTHER = "other", "其他"

    class ClaimType(models.TextChoices):
        OFFICIAL_FINDING = "official_finding", "官方结论"
        REPORTED_FACT = "reported_fact", "媒体事实报道"
        REPORTED_CLAIM = "reported_claim", "媒体转述指控"
        USER_ALLEGATION = "user_allegation", "用户指控"
        OPINION = "opinion", "观点"
        RUMOR = "rumor", "传闻"
        REBUTTAL = "rebuttal", "回应/澄清"

    class Status(models.TextChoices):
        SUSPECTED = "suspected", "疑似"
        REPORTED = "reported", "已报道"
        CONFIRMED = "confirmed", "已确认"
        DISPUTED = "disputed", "存在争议"
        RESOLVED = "resolved", "已解决"
        RETRACTED = "retracted", "已撤回"
        FALSE_POSITIVE = "false_positive", "误判"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scan = models.ForeignKey(
        NegativeIndexScan,
        on_delete=models.CASCADE,
        related_name="events",
    )
    category = models.CharField(max_length=32, choices=Category.choices)
    claim_type = models.CharField(max_length=32, choices=ClaimType.choices)
    status = models.CharField(max_length=24, choices=Status.choices)
    title = models.CharField(max_length=500)
    summary = models.TextField(blank=True)
    severity_score = models.PositiveSmallIntegerField(default=0)
    evidence_score = models.PositiveSmallIntegerField(default=0)
    visibility_score = models.PositiveSmallIntegerField(default=0)
    freshness_score = models.PositiveSmallIntegerField(default=0)
    current_risk = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    source_count = models.PositiveIntegerField(default=0)
    independent_domain_count = models.PositiveIntegerField(default=0)
    first_seen_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    cluster_key = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "negative_events"
        ordering = ("-current_risk", "-last_seen_at", "id")
        indexes = [
            models.Index(
                fields=("scan", "category", "current_risk"),
                name="neg_event_category_idx",
            ),
            models.Index(
                fields=("scan", "status", "current_risk"),
                name="neg_event_status_idx",
            ),
            models.Index(
                fields=("scan", "last_seen_at"),
                name="neg_event_date_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("scan", "cluster_key"),
                name="neg_event_cluster_unique",
            ),
            models.CheckConstraint(
                condition=Q(severity_score__lte=100),
                name="neg_event_severity_lte100",
            ),
            models.CheckConstraint(
                condition=Q(evidence_score__lte=100),
                name="neg_event_evidence_lte100",
            ),
            models.CheckConstraint(
                condition=Q(visibility_score__lte=100),
                name="neg_event_visibility_lte100",
            ),
            models.CheckConstraint(
                condition=Q(freshness_score__lte=100),
                name="neg_event_freshness_lte100",
            ),
            models.CheckConstraint(
                condition=Q(current_risk__gte=0, current_risk__lte=100),
                name="neg_event_risk_range",
            ),
        ]


class NegativeIndexItem(models.Model):  # noqa: DJ008
    class VerificationStatus(models.TextChoices):
        NOT_REQUESTED = "not_requested", "未核验"
        SUCCEEDED = "succeeded", "已核验"
        FAILED = "failed", "核验失败"

    class ClassificationSource(models.TextChoices):
        AI = "ai", "AI摘要判定"
        RULE = "rule", "保守规则判定"
        VERIFIED_AI = "verified_ai", "正文核验后AI判定"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scan = models.ForeignKey(
        NegativeIndexScan,
        on_delete=models.CASCADE,
        related_name="items",
    )
    event = models.ForeignKey(
        NegativeEvent,
        on_delete=models.CASCADE,
        related_name="items",
    )
    original_url = models.URLField(max_length=4096)
    normalized_url = models.CharField(max_length=4096)
    domain = models.CharField(max_length=255)
    root_domain = models.CharField(max_length=255)
    website = models.CharField(max_length=500, blank=True)
    title = models.CharField(max_length=1000)
    snippet = models.TextField(blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    source_type = models.CharField(max_length=32)
    authority_score = models.PositiveSmallIntegerField(default=0)
    relevance_score = models.PositiveSmallIntegerField(default=0)
    visibility_score = models.PositiveSmallIntegerField(default=0)
    freshness_score = models.PositiveSmallIntegerField(default=0)
    best_rank = models.PositiveIntegerField(default=51)
    matched_query_count = models.PositiveIntegerField(default=1)
    rule_signal_score = models.PositiveSmallIntegerField(default=0)
    negative_confidence = models.PositiveSmallIntegerField(default=0)
    severity_score = models.PositiveSmallIntegerField(default=0)
    evidence_confidence = models.PositiveSmallIntegerField(default=0)
    category = models.CharField(
        max_length=32,
        choices=NegativeEvent.Category.choices,
    )
    claim_type = models.CharField(
        max_length=32,
        choices=NegativeEvent.ClaimType.choices,
    )
    event_status = models.CharField(
        max_length=24,
        choices=NegativeEvent.Status.choices,
    )
    event_title = models.CharField(max_length=500)
    ai_summary = models.TextField(blank=True)
    classification_source = models.CharField(
        max_length=20,
        choices=ClassificationSource.choices,
    )
    verification_status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices,
        default=VerificationStatus.NOT_REQUESTED,
    )
    verification_excerpt = models.TextField(blank=True)
    verification_error_code = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "negative_index_items"
        ordering = ("-severity_score", "-evidence_confidence", "best_rank", "id")
        indexes = [
            models.Index(
                fields=("scan", "category", "severity_score"),
                name="neg_item_category_idx",
            ),
            models.Index(
                fields=("scan", "root_domain"),
                name="neg_item_domain_idx",
            ),
            models.Index(
                fields=("event", "published_at"),
                name="neg_item_event_date_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("scan", "normalized_url"),
                name="neg_item_scan_url_unique",
            ),
            models.CheckConstraint(
                condition=Q(authority_score__lte=100),
                name="neg_item_authority_lte100",
            ),
            models.CheckConstraint(
                condition=Q(relevance_score__lte=100),
                name="neg_item_relevance_lte100",
            ),
            models.CheckConstraint(
                condition=Q(visibility_score__lte=100),
                name="neg_item_visibility_lte100",
            ),
            models.CheckConstraint(
                condition=Q(freshness_score__lte=100),
                name="neg_item_freshness_lte100",
            ),
            models.CheckConstraint(
                condition=Q(rule_signal_score__lte=100),
                name="neg_item_rule_lte100",
            ),
            models.CheckConstraint(
                condition=Q(negative_confidence__lte=100),
                name="neg_item_negative_lte100",
            ),
            models.CheckConstraint(
                condition=Q(severity_score__lte=100),
                name="neg_item_severity_lte100",
            ),
            models.CheckConstraint(
                condition=Q(evidence_confidence__lte=100),
                name="neg_item_evidence_lte100",
            ),
        ]


class NegativeIndexHit(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scan = models.ForeignKey(
        NegativeIndexScan,
        on_delete=models.CASCADE,
        related_name="hits",
    )
    item = models.ForeignKey(
        NegativeIndexItem,
        on_delete=models.CASCADE,
        related_name="hits",
    )
    query = models.CharField(max_length=200)
    rank = models.PositiveIntegerField()
    range_start = models.DateField(null=True, blank=True)
    range_end = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "negative_index_hits"
        ordering = ("scan_id", "query", "rank", "id")
        indexes = [
            models.Index(
                fields=("scan", "query", "rank"),
                name="neg_hit_query_rank_idx",
            ),
            models.Index(fields=("item", "rank"), name="neg_hit_item_rank_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "scan",
                    "item",
                    "query",
                    "range_start",
                    "range_end",
                ),
                name="neg_hit_item_query_unique",
                nulls_distinct=False,
            )
        ]
