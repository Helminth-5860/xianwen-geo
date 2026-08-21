from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.db.models import F, Q


class ProtectedDetectionQuerySet(models.QuerySet):
    def delete(self):
        raise TypeError("GEO detection history cannot be deleted.")


class GeoDetectionJob(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        PARTIAL = "partial", "Partial"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="geo_detection_jobs"
    )
    subject = models.ForeignKey(
        "subjects.Subject", on_delete=models.PROTECT, related_name="geo_detection_jobs"
    )
    subscription = models.ForeignKey(
        "plans.Subscription", on_delete=models.PROTECT, related_name="geo_detection_jobs"
    )
    quota_hold = models.OneToOneField(
        "quotas.QuotaHoldGroup",
        on_delete=models.PROTECT,
        related_name="geo_detection_job",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    mode = models.CharField(max_length=16, default="new")
    planned_question_count = models.PositiveIntegerField()
    planned_model_count = models.PositiveIntegerField()
    planned_detection_points = models.PositiveBigIntegerField()
    completed_calls = models.PositiveBigIntegerField(default=0)
    successful_calls = models.PositiveBigIntegerField(default=0)
    failed_calls = models.PositiveBigIntegerField(default=0)
    cancelled_calls = models.PositiveBigIntegerField(default=0)
    queue_priority = models.PositiveIntegerField()
    idempotency_key_version = models.PositiveSmallIntegerField(default=1)
    idempotency_key_digest = models.CharField(max_length=64, unique=True)
    request_digest = models.CharField(max_length=64)
    request_id = models.UUIDField()
    cancel_requested_at = models.DateTimeField(null=True, blank=True)
    queued_at = models.DateTimeField()
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProtectedDetectionQuerySet.as_manager()

    class Meta:
        db_table = "geo_detection_jobs"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("user", "status", "created_at"), name="geo_job_user_status_idx"),
            models.Index(
                fields=("status", "queue_priority", "queued_at"), name="geo_job_queue_idx"
            ),
            models.Index(fields=("subject", "created_at"), name="geo_job_subject_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    status__in=("queued", "running", "partial", "succeeded", "failed", "cancelled")
                ),
                name="geo_job_status_valid",
            ),
            models.CheckConstraint(condition=Q(mode="new"), name="geo_job_mode_valid"),
            models.CheckConstraint(
                condition=Q(planned_question_count__gte=1), name="geo_job_questions_gte_1"
            ),
            models.CheckConstraint(
                condition=Q(planned_model_count__gte=1), name="geo_job_models_gte_1"
            ),
            models.CheckConstraint(
                condition=Q(planned_detection_points__gte=1), name="geo_job_points_gte_1"
            ),
            models.CheckConstraint(
                condition=Q(
                    planned_detection_points=F("planned_question_count") * F("planned_model_count")
                ),
                name="geo_job_points_match_matrix",
            ),
            models.CheckConstraint(
                condition=Q(queue_priority__gte=0, queue_priority__lte=1000),
                name="geo_job_priority_range",
            ),
            models.CheckConstraint(condition=Q(version__gte=1), name="geo_job_version_gte_1"),
            models.CheckConstraint(
                condition=Q(
                    completed_calls=F("successful_calls") + F("failed_calls") + F("cancelled_calls")
                ),
                name="geo_job_completed_sum",
            ),
            models.CheckConstraint(
                condition=Q(completed_calls__lte=F("planned_detection_points")),
                name="geo_job_completed_lte_planned",
            ),
        ]

    def delete(self, *args, **kwargs):
        raise TypeError("GEO detection jobs cannot be deleted.")


class ImmutableSnapshotQuerySet(ProtectedDetectionQuerySet):
    def update(self, **kwargs):
        raise TypeError("Detection snapshots are immutable.")

    def delete(self):
        raise TypeError("Detection snapshots are immutable.")


class GeoDetectionSnapshot(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.OneToOneField(GeoDetectionJob, on_delete=models.PROTECT, related_name="snapshot")
    subject_version = models.ForeignKey(
        "subjects.SubjectVersion", on_delete=models.PROTECT, related_name="geo_detection_snapshots"
    )
    keyword_set_version = models.ForeignKey(
        "keywords.KeywordSetVersion",
        on_delete=models.PROTECT,
        related_name="geo_detection_snapshots",
    )
    distillation_set = models.ForeignKey(
        "keywords.DistillationSet", on_delete=models.PROTECT, related_name="geo_detection_snapshots"
    )
    question_bank_version = models.ForeignKey(
        "questions.QuestionBankVersion",
        on_delete=models.PROTECT,
        related_name="geo_detection_snapshots",
    )
    entitlement_snapshot = models.JSONField()
    model_snapshots = models.JSONField()
    system_prompt = models.TextField()
    prompt_version = models.CharField(max_length=64)
    scoring_rule_version = models.CharField(max_length=64)
    input_digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableSnapshotQuerySet.as_manager()

    class Meta:
        db_table = "geo_detection_snapshots"
        constraints = [
            models.CheckConstraint(
                condition=~Q(input_digest=""), name="geo_snapshot_digest_present"
            ),
            models.CheckConstraint(
                condition=~Q(prompt_version=""), name="geo_snapshot_prompt_present"
            ),
            models.CheckConstraint(
                condition=~Q(scoring_rule_version=""), name="geo_snapshot_scoring_present"
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Detection snapshots are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Detection snapshots are immutable.")


class GeoDetectionQuestionSnapshot(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    snapshot = models.ForeignKey(
        GeoDetectionSnapshot, on_delete=models.PROTECT, related_name="questions"
    )
    source_question = models.ForeignKey(
        "questions.Question", on_delete=models.PROTECT, related_name="geo_detection_snapshots"
    )
    text = models.CharField(max_length=1000)
    primary_category_key = models.CharField(max_length=100)
    primary_category_name = models.CharField(max_length=150)
    primary_category_version = models.PositiveBigIntegerField()
    priority = models.CharField(max_length=16)
    question_type = models.CharField(max_length=24)
    participates_in_scoring = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField()

    objects = ImmutableSnapshotQuerySet.as_manager()

    class Meta:
        db_table = "geo_detection_question_snapshots"
        ordering = ("snapshot_id", "sort_order", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("snapshot", "source_question"), name="geo_question_snapshot_unique"
            ),
            models.UniqueConstraint(
                fields=("snapshot", "sort_order"), name="geo_question_snapshot_sort_unique"
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Detection question snapshots are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Detection question snapshots are immutable.")


class GeoDetectionModelRun(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        PARTIAL = "partial", "Partial"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(GeoDetectionJob, on_delete=models.PROTECT, related_name="model_runs")
    model = models.ForeignKey("ai.AIModel", on_delete=models.PROTECT, related_name="geo_model_runs")
    provider_key = models.CharField(max_length=100)
    model_key = models.CharField(max_length=100)
    provider_model_id = models.CharField(max_length=255)
    runtime_snapshot = models.JSONField()
    adapter_version = models.CharField(max_length=100)
    prompt_version = models.CharField(max_length=100)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    planned_calls = models.PositiveIntegerField()
    completed_calls = models.PositiveIntegerField(default=0)
    successful_calls = models.PositiveIntegerField(default=0)
    failed_calls = models.PositiveIntegerField(default=0)
    cancelled_calls = models.PositiveIntegerField(default=0)
    web_search_used_count = models.PositiveIntegerField(default=0)
    degraded_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProtectedDetectionQuerySet.as_manager()

    class Meta:
        db_table = "geo_detection_model_runs"
        ordering = ("job_id", "model_id")
        constraints = [
            models.UniqueConstraint(fields=("job", "model"), name="geo_model_run_unique"),
            models.CheckConstraint(
                condition=Q(
                    status__in=("queued", "running", "partial", "succeeded", "failed", "cancelled")
                ),
                name="geo_model_run_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(planned_calls__gte=1), name="geo_model_run_planned_gte_1"
            ),
            models.CheckConstraint(
                condition=Q(
                    completed_calls=F("successful_calls") + F("failed_calls") + F("cancelled_calls")
                ),
                name="geo_model_run_completed_sum",
            ),
            models.CheckConstraint(
                condition=Q(completed_calls__lte=F("planned_calls")),
                name="geo_model_run_completed_lte_planned",
            ),
        ]


class ModelCall(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        RETRY_WAIT = "retry_wait", "Retry wait"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    class Settlement(models.TextChoices):
        PENDING = "pending", "Pending"
        CONSUMED = "consumed", "Consumed"
        RELEASED = "released", "Released"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(GeoDetectionJob, on_delete=models.PROTECT, related_name="model_calls")
    model_run = models.ForeignKey(
        GeoDetectionModelRun, on_delete=models.PROTECT, related_name="calls"
    )
    question_snapshot = models.ForeignKey(
        GeoDetectionQuestionSnapshot, on_delete=models.PROTECT, related_name="model_calls"
    )
    model = models.ForeignKey(
        "ai.AIModel", on_delete=models.PROTECT, related_name="geo_model_calls"
    )
    provider_key = models.CharField(max_length=100)
    model_key = models.CharField(max_length=100)
    provider_model_id = models.CharField(max_length=255)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    settlement_status = models.CharField(
        max_length=16, choices=Settlement.choices, default=Settlement.PENDING
    )
    attempt_count = models.PositiveIntegerField(default=0)
    generation = models.UUIDField(null=True, blank=True)
    web_search_requested = models.BooleanField(default=False)
    web_search_used = models.BooleanField(default=False)
    degraded = models.BooleanField(default=False)
    finish_reason = models.CharField(max_length=32, blank=True)
    provider_request_id = models.CharField(max_length=128, blank=True)
    stable_error_code = models.CharField(max_length=100, blank=True)
    safe_error_summary = models.JSONField(default=dict)
    input_tokens = models.PositiveBigIntegerField(null=True, blank=True)
    output_tokens = models.PositiveBigIntegerField(null=True, blank=True)
    total_tokens = models.PositiveBigIntegerField(null=True, blank=True)
    latency_ms = models.PositiveBigIntegerField(null=True, blank=True)
    estimated_cost = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    cost_currency = models.CharField(max_length=3, blank=True)
    queued_at = models.DateTimeField()
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProtectedDetectionQuerySet.as_manager()

    class Meta:
        db_table = "model_calls"
        ordering = ("job_id", "queued_at", "id")
        indexes = [
            models.Index(
                fields=("status", "next_attempt_at", "queued_at"), name="model_call_due_idx"
            ),
            models.Index(fields=("job", "status"), name="model_call_job_status_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("job", "question_snapshot", "model"), name="model_call_unique"
            ),
            models.CheckConstraint(
                condition=Q(
                    status__in=(
                        "queued",
                        "running",
                        "retry_wait",
                        "succeeded",
                        "failed",
                        "cancelled",
                    )
                ),
                name="model_call_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(settlement_status__in=("pending", "consumed", "released")),
                name="model_call_settlement_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="succeeded", settlement_status="consumed") | ~Q(status="succeeded")
                ),
                name="model_call_success_consumed",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status__in=("failed", "cancelled"), settlement_status="released")
                    | ~Q(status__in=("failed", "cancelled"))
                ),
                name="model_call_terminal_released",
            ),
        ]


class ModelCallAttempt(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    model_call = models.ForeignKey(ModelCall, on_delete=models.PROTECT, related_name="attempts")
    attempt_no = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices)
    provider_request_id = models.CharField(max_length=128, blank=True)
    error_category = models.CharField(max_length=64, blank=True)
    stable_error_code = models.CharField(max_length=100, blank=True)
    retryable = models.BooleanField(default=False)
    input_tokens = models.PositiveBigIntegerField(null=True, blank=True)
    output_tokens = models.PositiveBigIntegerField(null=True, blank=True)
    total_tokens = models.PositiveBigIntegerField(null=True, blank=True)
    latency_ms = models.PositiveBigIntegerField(null=True, blank=True)
    finish_reason = models.CharField(max_length=32, blank=True)
    provider_metadata = models.JSONField(default=dict)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ProtectedDetectionQuerySet.as_manager()

    class Meta:
        db_table = "model_call_attempts"
        ordering = ("model_call_id", "attempt_no", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("model_call", "attempt_no"), name="model_call_attempt_unique"
            ),
            models.CheckConstraint(
                condition=Q(attempt_no__gte=1), name="model_call_attempt_no_gte_1"
            ),
            models.CheckConstraint(
                condition=Q(status__in=("running", "succeeded", "failed")),
                name="model_call_attempt_status_valid",
            ),
        ]


class ModelResponse(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    model_call = models.OneToOneField(ModelCall, on_delete=models.PROTECT, related_name="response")
    provider_model_id = models.CharField(max_length=255)
    raw_text = models.TextField()
    raw_text_sha256 = models.CharField(max_length=64)
    provider_metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableSnapshotQuerySet.as_manager()

    class Meta:
        db_table = "model_responses"
        constraints = [
            models.CheckConstraint(condition=~Q(raw_text=""), name="model_response_text_present"),
            models.CheckConstraint(
                condition=~Q(raw_text_sha256=""), name="model_response_hash_present"
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Model responses are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Model responses are immutable.")


class ModelResponseCitation(models.Model):  # noqa: DJ008
    class UrlStatus(models.TextChoices):
        SAFE = "safe", "Safe"
        MISSING = "missing", "Missing"
        INVALID = "invalid", "Invalid"
        BLOCKED = "blocked", "Blocked"
        UNRESOLVED = "unresolved", "Unresolved"

    class SourceCategory(models.TextChoices):
        UNKNOWN = "unknown", "Unknown"
        WEB = "web", "Web"

    class ExtractionMethod(models.TextChoices):
        PROVIDER = "provider", "Provider"
        RAW_TEXT = "raw_text", "Raw text"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    model_response = models.ForeignKey(
        ModelResponse,
        on_delete=models.PROTECT,
        related_name="citations",
    )
    sort_order = models.PositiveIntegerField()
    title = models.CharField(max_length=500, blank=True, default="")
    canonical_url = models.TextField(blank=True, default="")
    source_name = models.CharField(max_length=500, blank=True, default="")
    source_host = models.CharField(max_length=253, blank=True, default="")
    quoted_text = models.TextField(blank=True, default="")
    provider_rank = models.PositiveIntegerField(null=True, blank=True)
    url_status = models.CharField(max_length=16, choices=UrlStatus.choices)
    source_category = models.CharField(
        max_length=24,
        choices=SourceCategory.choices,
        default=SourceCategory.UNKNOWN,
    )
    extraction_method = models.CharField(max_length=16, choices=ExtractionMethod.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableSnapshotQuerySet.as_manager()

    class Meta:
        db_table = "model_response_citations"
        ordering = ("model_response_id", "sort_order", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("model_response", "sort_order"),
                name="model_response_citation_sort_unique",
            ),
            models.CheckConstraint(
                condition=Q(provider_rank__isnull=True) | Q(provider_rank__gte=1),
                name="model_response_citation_rank_valid",
            ),
            models.CheckConstraint(
                condition=Q(url_status__in=("safe", "missing", "invalid", "blocked", "unresolved")),
                name="model_response_citation_status_valid",
            ),
            models.CheckConstraint(
                condition=~Q(url_status="safe") | (~Q(canonical_url="") & ~Q(source_host="")),
                name="model_response_citation_safe_url_present",
            ),
            models.CheckConstraint(
                condition=Q(url_status="safe") | Q(canonical_url=""),
                name="model_response_citation_unsafe_url_hidden",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Model response citations are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Model response citations are immutable.")


class ProgrammaticScoreResult(models.Model):  # noqa: DJ008
    class RankResolution(models.TextChoices):
        DETERMINISTIC = "deterministic", "Deterministic"
        SEMANTIC_REQUIRED = "semantic_required", "Semantic required"
        NOT_APPLICABLE = "not_applicable", "Not applicable"

    class CitationResolution(models.TextChoices):
        DETERMINISTIC = "deterministic", "Deterministic"
        SEMANTIC_REQUIRED = "semantic_required", "Semantic required"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    model_response = models.OneToOneField(
        ModelResponse,
        on_delete=models.PROTECT,
        related_name="programmatic_score",
    )
    scoring_rule_version = models.CharField(max_length=64)
    question_type = models.CharField(max_length=24)
    mention_score = models.PositiveSmallIntegerField(null=True, blank=True)
    matched_kind = models.CharField(max_length=32, blank=True, default="")
    matched_value = models.CharField(max_length=500, blank=True, default="")
    rank_position = models.PositiveIntegerField(null=True, blank=True)
    rank_score = models.PositiveSmallIntegerField(null=True, blank=True)
    rank_resolution = models.CharField(max_length=24, choices=RankResolution.choices)
    citation_base_score = models.PositiveSmallIntegerField(null=True, blank=True)
    citation_resolution = models.CharField(max_length=24, choices=CitationResolution.choices)
    citation_evidence_count = models.PositiveIntegerField(default=0)
    evidence = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableSnapshotQuerySet.as_manager()

    class Meta:
        db_table = "programmatic_score_results"
        constraints = [
            models.CheckConstraint(
                condition=~Q(scoring_rule_version=""),
                name="programmatic_score_rule_present",
            ),
            models.CheckConstraint(
                condition=Q(question_type__in=("natural", "brand_directed")),
                name="programmatic_score_question_type_valid",
            ),
            models.CheckConstraint(
                condition=Q(mention_score__isnull=True) | Q(mention_score__in=(0, 100)),
                name="programmatic_score_mention_valid",
            ),
            models.CheckConstraint(
                condition=Q(rank_position__isnull=True) | Q(rank_position__gte=1),
                name="programmatic_score_rank_position_valid",
            ),
            models.CheckConstraint(
                condition=Q(rank_score__isnull=True) | Q(rank_score__in=(0, 20, 40, 60, 80, 100)),
                name="programmatic_score_rank_valid",
            ),
            models.CheckConstraint(
                condition=Q(citation_base_score__isnull=True) | Q(citation_base_score__in=(0, 20)),
                name="programmatic_score_citation_base_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        question_type="brand_directed",
                        mention_score__isnull=True,
                        rank_score__isnull=True,
                        rank_position__isnull=True,
                        rank_resolution="not_applicable",
                    )
                    | Q(question_type="natural")
                ),
                name="programmatic_score_brand_na_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(rank_resolution="deterministic", rank_score__isnull=False)
                    | Q(
                        rank_resolution__in=("semantic_required", "not_applicable"),
                        rank_score__isnull=True,
                    )
                ),
                name="programmatic_score_rank_resolution_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(citation_resolution="deterministic", citation_base_score__isnull=False)
                    | Q(
                        citation_resolution="semantic_required",
                        citation_base_score__isnull=True,
                    )
                ),
                name="programmatic_score_citation_resolution_valid",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Programmatic score results are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Programmatic score results are immutable.")


class ScoreResult(models.Model):  # noqa: DJ008
    class Track(models.TextChoices):
        GEO = "geo", "GEO"
        BRAND_REPUTATION = "brand_reputation", "Brand reputation"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    model_response = models.OneToOneField(
        ModelResponse,
        on_delete=models.PROTECT,
        related_name="score_result",
    )
    question_type = models.CharField(max_length=24)
    track = models.CharField(max_length=24, choices=Track.choices)
    mention_score = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    recommendation_score = models.DecimalField(max_digits=7, decimal_places=4)
    rank_score = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    accuracy_score = models.DecimalField(max_digits=7, decimal_places=4)
    sentiment_score = models.DecimalField(max_digits=7, decimal_places=4)
    citation_score = models.DecimalField(max_digits=7, decimal_places=4)
    total_score = models.DecimalField(max_digits=7, decimal_places=4)
    scoring_rule_version = models.CharField(max_length=64)
    semantic_schema_version = models.CharField(max_length=64)
    semantic_provider_key = models.CharField(max_length=100)
    semantic_model_key = models.CharField(max_length=100)
    semantic_adapter_version = models.CharField(max_length=100)
    semantic_prompt_version = models.CharField(max_length=100)
    semantic_provider_model_id = models.CharField(max_length=255)
    semantic_output_digest = models.CharField(max_length=64)
    evidence = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableSnapshotQuerySet.as_manager()

    class Meta:
        db_table = "score_results"
        constraints = [
            models.CheckConstraint(
                condition=Q(question_type__in=("natural", "brand_directed")),
                name="score_result_qtype_valid",
            ),
            models.CheckConstraint(
                condition=Q(track__in=("geo", "brand_reputation")),
                name="score_result_track_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        question_type="natural",
                        track="geo",
                        mention_score__isnull=False,
                        rank_score__isnull=False,
                    )
                    | Q(
                        question_type="brand_directed",
                        track="brand_reputation",
                        mention_score__isnull=True,
                        rank_score__isnull=True,
                    )
                ),
                name="score_result_track_shape",
            ),
            models.CheckConstraint(
                condition=Q(recommendation_score__gte=0, recommendation_score__lte=100),
                name="score_result_recommend_range",
            ),
            models.CheckConstraint(
                condition=Q(accuracy_score__gte=0, accuracy_score__lte=100),
                name="score_result_accuracy_range",
            ),
            models.CheckConstraint(
                condition=Q(sentiment_score__gte=0, sentiment_score__lte=100),
                name="score_result_sentiment_range",
            ),
            models.CheckConstraint(
                condition=Q(citation_score__gte=0, citation_score__lte=100),
                name="score_result_citation_range",
            ),
            models.CheckConstraint(
                condition=Q(total_score__gte=0, total_score__lte=100),
                name="score_result_total_range",
            ),
            models.CheckConstraint(
                condition=Q(mention_score__isnull=True)
                | Q(mention_score__gte=0, mention_score__lte=100),
                name="score_result_mention_range",
            ),
            models.CheckConstraint(
                condition=Q(rank_score__isnull=True) | Q(rank_score__gte=0, rank_score__lte=100),
                name="score_result_rank_range",
            ),
            models.CheckConstraint(
                condition=~Q(scoring_rule_version=""),
                name="score_result_rule_present",
            ),
            models.CheckConstraint(
                condition=~Q(semantic_schema_version=""),
                name="score_result_schema_present",
            ),
            models.CheckConstraint(
                condition=~Q(semantic_provider_key="")
                & ~Q(semantic_model_key="")
                & ~Q(semantic_adapter_version="")
                & ~Q(semantic_prompt_version="")
                & ~Q(semantic_provider_model_id="")
                & ~Q(semantic_output_digest=""),
                name="score_result_provenance_present",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Score results are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Score results are immutable.")


class ModelScoreResult(models.Model):  # noqa: DJ008
    class Track(models.TextChoices):
        GEO = "geo", "GEO"
        BRAND_REPUTATION = "brand_reputation", "Brand reputation"

    class Status(models.TextChoices):
        FORMAL = "formal", "Formal"
        REFERENCE = "reference", "Reference"
        NOT_GENERATED = "not_generated", "Not generated"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    model_run = models.ForeignKey(
        GeoDetectionModelRun,
        on_delete=models.PROTECT,
        related_name="score_results",
    )
    track = models.CharField(max_length=24, choices=Track.choices)
    planned_count = models.PositiveIntegerField()
    successful_count = models.PositiveIntegerField()
    success_rate = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    score = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices)
    scoring_rule_version = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableSnapshotQuerySet.as_manager()

    class Meta:
        db_table = "model_scores"
        constraints = [
            models.UniqueConstraint(
                fields=("model_run", "track"),
                name="model_score_unique",
            ),
            models.CheckConstraint(
                condition=Q(track__in=("geo", "brand_reputation")),
                name="model_score_track_valid",
            ),
            models.CheckConstraint(
                condition=Q(status__in=("formal", "reference", "not_generated")),
                name="model_score_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(successful_count__lte=models.F("planned_count")),
                name="model_score_counts_valid",
            ),
            models.CheckConstraint(
                condition=Q(success_rate__isnull=True)
                | Q(success_rate__gte=0, success_rate__lte=100),
                name="model_score_rate_range",
            ),
            models.CheckConstraint(
                condition=Q(score__isnull=True) | Q(score__gte=0, score__lte=100),
                name="model_score_value_range",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status="not_generated",
                        planned_count=0,
                        successful_count=0,
                        success_rate__isnull=True,
                        score__isnull=True,
                    )
                    | Q(
                        status__in=("formal", "reference"),
                        planned_count__gte=1,
                        success_rate__isnull=False,
                    )
                ),
                name="model_score_state_valid",
            ),
            models.CheckConstraint(
                condition=~Q(scoring_rule_version=""),
                name="model_score_rule_present",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Model score results are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Model score results are immutable.")


class CompetitorEntity(models.Model):  # noqa: DJ008
    class EntityType(models.TextChoices):
        BRAND = "brand", "Brand"
        COMPANY = "company", "Company"
        PRODUCT = "product", "Product"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(
        GeoDetectionJob, on_delete=models.PROTECT, related_name="competitor_entities"
    )
    canonical_name = models.CharField(max_length=255)
    canonical_key = models.CharField(max_length=255)
    aliases = models.JSONField(default=list)
    entity_type = models.CharField(max_length=16, choices=EntityType.choices)
    semantic_schema_version = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableSnapshotQuerySet.as_manager()

    class Meta:
        db_table = "competitor_entities"
        constraints = [
            models.UniqueConstraint(
                fields=("job", "canonical_key"), name="competitor_entity_job_key_unique"
            ),
            models.CheckConstraint(
                condition=Q(entity_type__in=("brand", "company", "product")),
                name="competitor_entity_type_valid",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Competitor entities are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Competitor entities are immutable.")


class CompetitorMention(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity = models.ForeignKey(CompetitorEntity, on_delete=models.PROTECT, related_name="mentions")
    score_result = models.ForeignKey(
        ScoreResult, on_delete=models.PROTECT, related_name="competitor_mentions"
    )
    question = models.CharField(max_length=1000)
    model_key = models.CharField(max_length=100)
    occurrence = models.PositiveIntegerField()
    recommendation_score = models.DecimalField(max_digits=7, decimal_places=4)
    subject_rank = models.PositiveIntegerField(null=True, blank=True)
    competitor_rank = models.PositiveIntegerField(null=True, blank=True)
    rank_gap = models.IntegerField(null=True, blank=True)
    evidence = models.JSONField(default=dict)
    provenance = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableSnapshotQuerySet.as_manager()

    class Meta:
        db_table = "competitor_mentions"
        constraints = [
            models.UniqueConstraint(
                fields=("entity", "score_result"), name="competitor_mention_score_unique"
            ),
            models.CheckConstraint(
                condition=Q(occurrence__gte=1), name="competitor_mention_occurrence_gte_1"
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Competitor mentions are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Competitor mentions are immutable.")


class CompetitorDisposition(models.Model):  # noqa: DJ008
    class Decision(models.TextChoices):
        COMPETITOR = "competitor", "Competitor"
        NOT_COMPETITOR = "not_competitor", "Not competitor"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity = models.ForeignKey(
        CompetitorEntity, on_delete=models.PROTECT, related_name="dispositions"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="competitor_dispositions",
    )
    decision = models.CharField(max_length=24, choices=Decision.choices)
    note = models.CharField(max_length=1000, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableSnapshotQuerySet.as_manager()

    class Meta:
        db_table = "competitor_dispositions"
        ordering = ("entity_id", "created_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(decision__in=("competitor", "not_competitor")),
                name="competitor_disposition_decision_valid",
            )
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Competitor dispositions are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Competitor dispositions are append-only.")


class GeoReport(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.OneToOneField(GeoDetectionJob, on_delete=models.PROTECT, related_name="report")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="geo_reports"
    )
    subject = models.ForeignKey(
        "subjects.Subject", on_delete=models.PROTECT, related_name="geo_reports"
    )
    subject_version = models.ForeignKey(
        "subjects.SubjectVersion", on_delete=models.PROTECT, related_name="geo_reports"
    )
    baseline_report = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="retests"
    )
    retest_mode = models.CharField(max_length=16, blank=True, default="")
    question_signature = models.CharField(max_length=64)
    model_signature = models.CharField(max_length=64)
    scoring_rule_version = models.CharField(max_length=64)
    summary = models.JSONField()
    provenance = models.JSONField()
    generated_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableSnapshotQuerySet.as_manager()

    class Meta:
        db_table = "geo_reports"
        ordering = ("-generated_at", "-id")
        constraints = [
            models.CheckConstraint(
                condition=Q(retest_mode__in=("", "quick", "adjusted")),
                name="geo_report_retest_mode_valid",
            ),
            models.CheckConstraint(
                condition=~Q(question_signature=""), name="geo_report_question_sig_present"
            ),
            models.CheckConstraint(
                condition=~Q(model_signature=""), name="geo_report_model_sig_present"
            ),
            models.CheckConstraint(
                condition=~Q(scoring_rule_version=""), name="geo_report_rule_present"
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("GEO reports are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("GEO reports are immutable.")


class ReportExport(models.Model):  # noqa: DJ008
    class Format(models.TextChoices):
        PDF = "pdf", "PDF"
        WORD = "word", "Word"
        EXCEL = "excel", "Excel"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report = models.ForeignKey(GeoReport, on_delete=models.PROTECT, related_name="exports")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="report_exports"
    )
    format = models.CharField(max_length=16, choices=Format.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    brand_snapshot = models.JSONField(default=dict)
    object_key = models.CharField(max_length=500, blank=True, default="")
    safe_error_code = models.CharField(max_length=100, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    objects = ProtectedDetectionQuerySet.as_manager()

    class Meta:
        db_table = "report_exports"
        ordering = ("-created_at", "-id")
        constraints = [
            models.CheckConstraint(
                condition=Q(format__in=("pdf", "word", "excel")),
                name="report_export_format_valid",
            ),
            models.CheckConstraint(
                condition=Q(status__in=("queued", "running", "succeeded", "failed")),
                name="report_export_status_valid",
            ),
        ]

    def delete(self, *args, **kwargs):
        raise TypeError("Report export history cannot be deleted.")


class DetectionRetest(models.Model):  # noqa: DJ008
    class Mode(models.TextChoices):
        QUICK = "quick", "Quick"
        ADJUSTED = "adjusted", "Adjusted"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.OneToOneField(
        GeoDetectionJob, on_delete=models.PROTECT, related_name="retest_origin"
    )
    baseline_report = models.ForeignKey(
        GeoReport, on_delete=models.PROTECT, related_name="detection_retests"
    )
    mode = models.CharField(max_length=16, choices=Mode.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableSnapshotQuerySet.as_manager()

    class Meta:
        db_table = "geo_detection_retests"
        constraints = [
            models.CheckConstraint(
                condition=Q(mode__in=("quick", "adjusted")),
                name="geo_detection_retest_mode_valid",
            )
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Detection retest provenance is immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Detection retest provenance is immutable.")


class LifecycleEvidenceQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError("AI lifecycle evidence must use guarded model transitions.")

    def delete(self):
        raise TypeError("AI lifecycle evidence cannot be deleted.")


class StrategyReport(models.Model):  # noqa: DJ008
    class Period(models.TextChoices):
        DAYS_7 = "7d", "7 days"
        DAYS_30 = "30d", "30 days"
        DAYS_90 = "90d", "90 days"
        CUSTOM = "custom", "Custom"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    class BillingMode(models.TextChoices):
        FREE_INITIAL = "free_initial", "First strategy for report"
        REGENERATION = "regeneration", "Regeneration"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report = models.ForeignKey(GeoReport, on_delete=models.PROTECT, related_name="strategies")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="strategy_reports"
    )
    subject = models.ForeignKey(
        "subjects.Subject", on_delete=models.PROTECT, related_name="strategy_reports"
    )
    subject_version = models.ForeignKey(
        "subjects.SubjectVersion", on_delete=models.PROTECT, related_name="strategy_reports"
    )
    subscription = models.ForeignKey(
        "plans.Subscription", on_delete=models.PROTECT, related_name="strategy_reports"
    )
    quota_hold = models.OneToOneField(
        "quotas.QuotaHoldGroup",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="strategy_report",
    )
    period = models.CharField(max_length=16, choices=Period.choices)
    period_days = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    billing_mode = models.CharField(max_length=24, choices=BillingMode.choices)
    ai_body = models.JSONField(default=dict)
    report_facts = models.JSONField()
    provider_key = models.CharField(max_length=100)
    model_key = models.CharField(max_length=100)
    provider_model_id = models.CharField(max_length=255)
    adapter_version = models.CharField(max_length=100)
    prompt_version = models.CharField(max_length=100)
    schema_version = models.CharField(max_length=100)
    input_digest = models.CharField(max_length=64)
    idempotency_key_digest = models.CharField(max_length=64, unique=True)
    request_digest = models.CharField(max_length=64)
    request_id = models.UUIDField()
    generation = models.UUIDField(default=uuid.uuid4)
    attempts = models.PositiveIntegerField(default=0)
    safe_error_code = models.CharField(max_length=100, blank=True, default="")
    usage_summary = models.JSONField(default=dict)
    started_at = models.DateTimeField(null=True, blank=True)
    generated_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = LifecycleEvidenceQuerySet.as_manager()

    class Meta:
        db_table = "strategy_reports"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("user", "report", "created_at"), name="strategy_user_report_idx"),
            models.Index(fields=("status", "created_at"), name="strategy_status_created_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("report",),
                condition=Q(status__in=("queued", "running")),
                name="strategy_one_active_per_report",
            ),
            models.CheckConstraint(
                condition=Q(period__in=("7d", "30d", "90d", "custom")),
                name="strategy_period_valid",
            ),
            models.CheckConstraint(
                condition=Q(period_days__gte=1, period_days__lte=365),
                name="strategy_period_days_valid",
            ),
            models.CheckConstraint(
                condition=Q(status__in=("queued", "running", "succeeded", "failed")),
                name="strategy_status_valid",
            ),
            models.CheckConstraint(
                condition=(Q(billing_mode="free_initial", quota_hold__isnull=True))
                | Q(billing_mode="regeneration", quota_hold__isnull=False),
                name="strategy_billing_hold_valid",
            ),
        ]

    def save(self, *args, **kwargs):
        if self._state.adding:
            if (
                self.status != self.Status.QUEUED
                or self.attempts != 0
                or self.ai_body
                or self.usage_summary
                or self.safe_error_code
                or self.started_at is not None
                or self.generated_at is not None
                or self.finished_at is not None
            ):
                raise TypeError("Strategy reports must start in the queued state.")
        else:
            previous = StrategyReport.objects.get(pk=self.pk)
            frozen = (
                "report_id",
                "user_id",
                "subject_id",
                "subject_version_id",
                "subscription_id",
                "quota_hold_id",
                "period",
                "period_days",
                "billing_mode",
                "report_facts",
                "provider_key",
                "model_key",
                "provider_model_id",
                "adapter_version",
                "prompt_version",
                "schema_version",
                "input_digest",
                "idempotency_key_digest",
                "request_digest",
                "request_id",
            )
            if any(getattr(previous, field) != getattr(self, field) for field in frozen):
                raise TypeError("Strategy generation facts are immutable.")
            if previous.status in {self.Status.SUCCEEDED, self.Status.FAILED}:
                raise TypeError("Terminal strategy reports are immutable.")
            if previous.ai_body and previous.ai_body != self.ai_body:
                raise TypeError("Strategy AI output is immutable.")
            valid_transition = False
            if previous.status == self.Status.QUEUED and self.status == self.Status.RUNNING:
                valid_transition = (
                    self.attempts == previous.attempts + 1
                    and self.generation != previous.generation
                    and self.started_at is not None
                    and self.generated_at is None
                    and self.finished_at is None
                    and self.ai_body == previous.ai_body
                    and self.usage_summary == previous.usage_summary
                    and not self.safe_error_code
                )
            elif previous.status == self.Status.QUEUED and self.status == self.Status.FAILED:
                valid_transition = (
                    self.attempts == previous.attempts
                    and self.generation == previous.generation
                    and self.started_at == previous.started_at
                    and self.generated_at is None
                    and self.finished_at is not None
                    and self.ai_body == previous.ai_body
                    and self.usage_summary == previous.usage_summary
                    and bool(self.safe_error_code)
                )
            elif previous.status == self.Status.RUNNING and self.status == self.Status.SUCCEEDED:
                valid_transition = (
                    self.attempts == previous.attempts
                    and self.generation == previous.generation
                    and self.started_at == previous.started_at
                    and self.generated_at is not None
                    and self.finished_at is not None
                    and bool(self.ai_body)
                    and not previous.ai_body
                    and not self.safe_error_code
                )
            elif previous.status == self.Status.RUNNING and self.status == self.Status.FAILED:
                valid_transition = (
                    self.attempts == previous.attempts
                    and self.generation == previous.generation
                    and self.started_at == previous.started_at
                    and self.generated_at is None
                    and self.finished_at is not None
                    and self.ai_body == previous.ai_body
                    and self.usage_summary == previous.usage_summary
                    and bool(self.safe_error_code)
                )
            if not valid_transition:
                raise TypeError("Invalid strategy report lifecycle transition.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Strategy history cannot be deleted.")


class StrategyNote(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    strategy = models.OneToOneField(StrategyReport, on_delete=models.CASCADE, related_name="note")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="strategy_notes"
    )
    text = models.TextField(blank=True, default="")
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "strategy_notes"
        constraints = [
            models.CheckConstraint(condition=Q(version__gte=1), name="strategy_note_version_gte_1")
        ]


class AssistantUsageEvent(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        REFUSED = "refused", "Refused"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="assistant_usage_events"
    )
    subject = models.ForeignKey(
        "subjects.Subject", on_delete=models.PROTECT, related_name="assistant_usage_events"
    )
    subject_version = models.ForeignKey(
        "subjects.SubjectVersion",
        on_delete=models.PROTECT,
        related_name="assistant_usage_events",
    )
    subscription = models.ForeignKey(
        "plans.Subscription", on_delete=models.PROTECT, related_name="assistant_usage_events"
    )
    quota_hold = models.OneToOneField(
        "quotas.QuotaHoldGroup",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="assistant_usage_event",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    provider_key = models.CharField(max_length=100)
    model_key = models.CharField(max_length=100)
    provider_model_id = models.CharField(max_length=255)
    adapter_version = models.CharField(max_length=100)
    prompt_version = models.CharField(max_length=100)
    schema_version = models.CharField(max_length=100)
    context_digest = models.CharField(max_length=64)
    idempotency_key_digest = models.CharField(max_length=64, unique=True)
    request_digest = models.CharField(max_length=64)
    request_id = models.UUIDField()
    safe_error_code = models.CharField(max_length=100, blank=True, default="")
    usage_summary = models.JSONField(default=dict)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = LifecycleEvidenceQuerySet.as_manager()

    class Meta:
        db_table = "assistant_usage_events"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("user", "subject", "created_at"), name="assistant_usage_scope_idx")
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=("pending", "succeeded", "failed", "refused")),
                name="assistant_usage_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(status="refused", quota_hold__isnull=True)
                | (~Q(status="refused") & Q(quota_hold__isnull=False)),
                name="assistant_usage_hold_valid",
            ),
        ]

    def save(self, *args, **kwargs):
        if self._state.adding:
            if self.status == self.Status.PENDING:
                valid_initial = (
                    self.quota_hold_id is not None
                    and not self.safe_error_code
                    and not self.usage_summary
                    and self.finished_at is None
                )
            else:
                valid_initial = (
                    self.status == self.Status.REFUSED
                    and self.quota_hold_id is None
                    and bool(self.safe_error_code)
                    and not self.usage_summary
                    and self.finished_at is not None
                )
            if not valid_initial:
                raise TypeError("Invalid initial assistant usage state.")
        else:
            previous = AssistantUsageEvent.objects.get(pk=self.pk)
            frozen = (
                "user_id",
                "subject_id",
                "subject_version_id",
                "subscription_id",
                "quota_hold_id",
                "provider_key",
                "model_key",
                "provider_model_id",
                "adapter_version",
                "prompt_version",
                "schema_version",
                "context_digest",
                "idempotency_key_digest",
                "request_digest",
                "request_id",
            )
            if any(getattr(previous, field) != getattr(self, field) for field in frozen):
                raise TypeError("Assistant usage facts are immutable.")
            if previous.status != self.Status.PENDING:
                raise TypeError("Terminal assistant usage is immutable.")
            if self.status == self.Status.SUCCEEDED:
                valid_transition = (
                    self.finished_at is not None
                    and not self.safe_error_code
                    and bool(self.usage_summary)
                )
            elif self.status == self.Status.FAILED:
                valid_transition = (
                    self.finished_at is not None
                    and bool(self.safe_error_code)
                    and self.usage_summary == previous.usage_summary
                )
            else:
                valid_transition = False
            if not valid_transition:
                raise TypeError("Invalid assistant usage lifecycle transition.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Assistant usage evidence cannot be deleted.")


class SubjectWhiteLabelConfig(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    subject = models.OneToOneField(
        "subjects.Subject", on_delete=models.PROTECT, related_name="white_label_config"
    )
    brand_name = models.CharField(max_length=100)
    logo_document_version = models.ForeignKey(
        "documents.DocumentVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="white_label_logos",
    )
    cover_document_version = models.ForeignKey(
        "documents.DocumentVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="white_label_covers",
    )
    primary_color = models.CharField(max_length=7, default="#1677ff")
    header_text = models.CharField(max_length=500, blank=True)
    footer_text = models.CharField(max_length=500, blank=True)
    contact = models.CharField(max_length=500, blank=True)
    statement = models.TextField(blank=True)
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "subject_white_label_configs"
        constraints = [
            models.CheckConstraint(condition=Q(version__gte=1), name="white_label_version_gte_1")
        ]


class ReportShare(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report = models.ForeignKey(GeoReport, on_delete=models.PROTECT, related_name="shares")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="report_shares"
    )
    subject = models.ForeignKey(
        "subjects.Subject", on_delete=models.PROTECT, related_name="report_shares"
    )
    token_digest = models.CharField(max_length=64, unique=True)
    report_snapshot = models.JSONField()
    report_snapshot_digest = models.CharField(max_length=64)
    brand_snapshot = models.JSONField()
    password_hash = models.CharField(max_length=255, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    access_count = models.PositiveBigIntegerField(default=0)
    last_accessed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "report_shares"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("user", "report", "created_at"), name="report_share_owner_idx")
        ]

    def delete(self, *args, **kwargs):
        raise TypeError("Report shares must be closed, not deleted.")


class ReportShareAccessLog(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    share = models.ForeignKey(ReportShare, on_delete=models.PROTECT, related_name="access_logs")
    ip_digest = models.CharField(max_length=64)
    user_agent = models.CharField(max_length=300, blank=True)
    result = models.CharField(max_length=32)
    accessed_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableSnapshotQuerySet.as_manager()

    class Meta:
        db_table = "report_share_access_logs"
        ordering = ("-accessed_at", "-id")
        indexes = [models.Index(fields=("share", "accessed_at"), name="share_access_time_idx")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Share access logs are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Share access logs are append-only.")
