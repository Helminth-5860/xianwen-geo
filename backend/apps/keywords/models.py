import uuid

from django.conf import settings
from django.db import models

from apps.subjects.models import Subject, SubjectVersion


class KeywordSetQuerySet(models.QuerySet):
    def delete(self):
        raise TypeError("Keyword sets cannot be deleted.")


class KeywordSet(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="keyword_sets",
    )
    subject = models.OneToOneField(
        Subject,
        on_delete=models.PROTECT,
        related_name="keyword_set",
    )
    draft_subject_version = models.ForeignKey(
        SubjectVersion,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="keyword_drafts",
    )
    current_version = models.ForeignKey(
        "KeywordSetVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="current_for_keyword_sets",
    )
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = KeywordSetQuerySet.as_manager()

    class Meta:
        db_table = "keyword_sets"
        ordering = ("subject_id", "id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="keyword_set_version_gte_1",
            )
        ]


class KeywordItemFields(models.Model):
    class StructureType(models.TextChoices):
        SHORT = "short", "短关键词"
        LONG_TAIL = "long_tail", "长尾关键词"
        GENERAL = "general", "通用关键词"

    class RegionLevel(models.TextChoices):
        COUNTRY = "country", "国家/地区"
        PROVINCE = "province", "省/州"
        CITY = "city", "城市"
        DISTRICT = "district", "区县"
        CUSTOM = "custom", "自定义"

    class SearchIntent(models.TextChoices):
        INFORMATIONAL = "informational", "Informational"
        NAVIGATIONAL = "navigational", "Navigational"
        COMMERCIAL = "commercial", "Commercial"
        TRANSACTIONAL = "transactional", "Transactional"

    class Priority(models.TextChoices):
        HIGH = "high", "High"
        MEDIUM = "medium", "Medium"
        LOW = "low", "Low"

    text = models.CharField(max_length=500)
    matching_text = models.CharField(max_length=500)
    structure_type = models.CharField(max_length=16, choices=StructureType.choices)
    is_regional = models.BooleanField(default=False)
    region_level = models.CharField(max_length=16, choices=RegionLevel.choices, blank=True)
    region_text = models.CharField(max_length=200, blank=True)
    region_matching_key = models.CharField(max_length=240, blank=True)
    business_category = models.CharField(  # noqa: DJ001
        max_length=128, null=True, blank=True
    )
    search_intent = models.CharField(  # noqa: DJ001
        max_length=16, choices=SearchIntent.choices, null=True, blank=True
    )
    relevance_score = models.PositiveSmallIntegerField(null=True, blank=True)
    priority = models.CharField(  # noqa: DJ001
        max_length=16, choices=Priority.choices, null=True, blank=True
    )
    ai_reason = models.CharField(  # noqa: DJ001
        max_length=1000, null=True, blank=True
    )
    sort_order = models.PositiveIntegerField()

    class Meta:
        abstract = True


class KeywordDraftItem(KeywordItemFields):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    keyword_set = models.ForeignKey(
        KeywordSet,
        on_delete=models.CASCADE,
        related_name="draft_items",
    )
    base_keyword_text = models.CharField(  # noqa: DJ001
        max_length=500, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "keyword_draft_items"
        ordering = ("keyword_set_id", "sort_order", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("keyword_set", "sort_order"),
                name="keyword_draft_sort_unique",
            ),
            models.UniqueConstraint(
                fields=("keyword_set", "matching_text", "region_matching_key"),
                name="keyword_draft_semantic_unique",
            ),
            models.CheckConstraint(
                condition=~models.Q(text="") & ~models.Q(matching_text=""),
                name="keyword_draft_text_present",
            ),
            models.CheckConstraint(
                condition=models.Q(structure_type__in=("short", "long_tail", "general")),
                name="keyword_draft_structure_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(search_intent__isnull=True)
                | models.Q(
                    search_intent__in=(
                        "informational",
                        "navigational",
                        "commercial",
                        "transactional",
                    )
                ),
                name="keyword_draft_intent_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(priority__isnull=True)
                | models.Q(priority__in=("high", "medium", "low")),
                name="keyword_draft_priority_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(relevance_score__isnull=True)
                | models.Q(relevance_score__lte=100),
                name="keyword_draft_relevance_lte_100",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(region_level="")
                    | models.Q(
                        region_level__in=("country", "province", "city", "district", "custom")
                    )
                ),
                name="keyword_draft_region_level_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        is_regional=False,
                        region_level="",
                        region_text="",
                        region_matching_key="",
                    )
                    | (
                        models.Q(is_regional=True)
                        & ~models.Q(region_text="")
                        & ~models.Q(region_matching_key="")
                    )
                ),
                name="keyword_draft_region_shape",
            ),
        ]


class AppendOnlyKeywordVersionQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError("Keyword versions are append-only.")

    def delete(self):
        raise TypeError("Keyword versions are append-only.")


class KeywordSetVersion(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    keyword_set = models.ForeignKey(
        KeywordSet,
        on_delete=models.PROTECT,
        related_name="versions",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="keyword_versions",
    )
    subject = models.ForeignKey(
        Subject,
        on_delete=models.PROTECT,
        related_name="keyword_versions",
    )
    subject_version = models.ForeignKey(
        SubjectVersion,
        on_delete=models.PROTECT,
        related_name="keyword_versions",
    )
    version_no = models.PositiveBigIntegerField()
    content_digest = models.CharField(max_length=64)
    item_count = models.PositiveIntegerField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_keyword_versions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlyKeywordVersionQuerySet.as_manager()

    class Meta:
        db_table = "keyword_set_versions"
        ordering = ("keyword_set_id", "version_no", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("keyword_set", "version_no"),
                name="keyword_version_number_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(version_no__gte=1),
                name="keyword_version_number_gte_1",
            ),
            models.CheckConstraint(
                condition=models.Q(item_count__gte=1),
                name="keyword_version_item_count_gte_1",
            ),
            models.CheckConstraint(
                condition=~models.Q(content_digest=""),
                name="keyword_version_digest_present",
            ),
        ]


class AppendOnlyKeywordQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError("Formal keywords are append-only.")

    def delete(self):
        raise TypeError("Formal keywords are append-only.")


class Keyword(KeywordItemFields):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    keyword_set_version = models.ForeignKey(
        KeywordSetVersion,
        on_delete=models.PROTECT,
        related_name="keywords",
    )
    base_keyword = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="derived_keywords"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlyKeywordQuerySet.as_manager()

    class Meta:
        db_table = "keywords"
        ordering = ("keyword_set_version_id", "sort_order", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("keyword_set_version", "sort_order"),
                name="keyword_formal_sort_unique",
            ),
            models.UniqueConstraint(
                fields=("keyword_set_version", "matching_text", "region_matching_key"),
                name="keyword_formal_semantic_unique",
            ),
            models.CheckConstraint(
                condition=~models.Q(text="") & ~models.Q(matching_text=""),
                name="keyword_formal_text_present",
            ),
            models.CheckConstraint(
                condition=models.Q(structure_type__in=("short", "long_tail", "general")),
                name="keyword_formal_structure_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(search_intent__isnull=True)
                | models.Q(
                    search_intent__in=(
                        "informational",
                        "navigational",
                        "commercial",
                        "transactional",
                    )
                ),
                name="keyword_formal_intent_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(priority__isnull=True)
                | models.Q(priority__in=("high", "medium", "low")),
                name="keyword_formal_priority_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(relevance_score__isnull=True)
                | models.Q(relevance_score__lte=100),
                name="keyword_formal_relevance_lte_100",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(region_level="")
                    | models.Q(
                        region_level__in=("country", "province", "city", "district", "custom")
                    )
                ),
                name="keyword_formal_region_level_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        is_regional=False,
                        region_level="",
                        region_text="",
                        region_matching_key="",
                    )
                    | (
                        models.Q(is_regional=True)
                        & ~models.Q(region_text="")
                        & ~models.Q(region_matching_key="")
                    )
                ),
                name="keyword_formal_region_shape",
            ),
        ]


class KeywordGenerationJobQuerySet(models.QuerySet):
    def delete(self):
        raise TypeError("Keyword generation jobs cannot be deleted.")


class KeywordGenerationImmutableQuerySet(KeywordGenerationJobQuerySet):
    def update(self, **kwargs):
        raise TypeError("Keyword generation evidence is append-only.")


class KeywordGenerationJob(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        RETRY_WAIT = "retry_wait", "Retry wait"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CONFLICT = "conflict", "Conflict"
        SUPERSEDED = "superseded", "Superseded"

    class BillingMode(models.TextChoices):
        FREE_INITIAL = "free_initial", "Free initial"
        REGENERATION = "regeneration", "Regeneration"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="keyword_generation_jobs"
    )
    subject = models.ForeignKey(
        Subject, on_delete=models.PROTECT, related_name="keyword_generation_jobs"
    )
    subject_version = models.ForeignKey(
        SubjectVersion, on_delete=models.PROTECT, related_name="keyword_generation_jobs"
    )
    keyword_set = models.ForeignKey(
        KeywordSet, null=True, blank=True, on_delete=models.PROTECT, related_name="generation_jobs"
    )
    subscription = models.ForeignKey(
        "plans.Subscription", on_delete=models.PROTECT, related_name="keyword_generation_jobs"
    )
    quota_hold = models.ForeignKey(
        "quotas.QuotaHoldGroup",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="keyword_generation_jobs",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    billing_mode = models.CharField(max_length=16, choices=BillingMode.choices)
    version = models.PositiveBigIntegerField(default=1)
    expected_keyword_set_version = models.PositiveBigIntegerField()
    target_count = models.PositiveIntegerField()
    include_short = models.BooleanField(default=False)
    include_long_tail = models.BooleanField(default=False)
    include_regional = models.BooleanField(default=False)
    regions = models.JSONField(default=list)
    input_subject_values = models.JSONField(default=dict)
    historical_exclusions = models.JSONField(default=list)
    provider_key = models.CharField(max_length=32)
    model_key = models.CharField(max_length=64)
    adapter_version = models.CharField(max_length=32)
    prompt_version = models.CharField(max_length=32)
    input_digest = models.CharField(max_length=64)
    idempotency_key_version = models.PositiveSmallIntegerField(default=1)
    idempotency_key_digest = models.CharField(max_length=64, unique=True)
    request_digest = models.CharField(max_length=64)
    generation = models.UUIDField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    retry_count = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    stable_error_code = models.CharField(max_length=64, blank=True)
    request_id = models.UUIDField(null=True, blank=True)
    correlation_id = models.UUIDField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = KeywordGenerationJobQuerySet.as_manager()

    class Meta:
        db_table = "keyword_generation_jobs"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("subject", "status", "created_at"), name="kw_gen_status_idx"),
            models.Index(fields=("status", "next_attempt_at"), name="kw_gen_retry_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("subject",),
                condition=models.Q(status__in=("queued", "running", "retry_wait")),
                name="keyword_generation_one_open",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=(
                        "queued",
                        "running",
                        "retry_wait",
                        "succeeded",
                        "failed",
                        "conflict",
                        "superseded",
                    )
                ),
                name="keyword_generation_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(billing_mode="free_initial", quota_hold__isnull=True)
                | models.Q(billing_mode="regeneration", quota_hold__isnull=False),
                name="keyword_generation_billing_hold",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1)
                & models.Q(target_count__gte=1)
                & models.Q(attempts__gte=0)
                & models.Q(retry_count__gte=0),
                name="keyword_generation_counts_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status="queued",
                        generation__isnull=True,
                        started_at__isnull=True,
                        finished_at__isnull=True,
                    )
                    | models.Q(
                        status="running",
                        generation__isnull=False,
                        started_at__isnull=False,
                        finished_at__isnull=True,
                    )
                    | models.Q(
                        status="retry_wait",
                        generation__isnull=False,
                        next_attempt_at__isnull=False,
                        finished_at__isnull=True,
                    )
                    | models.Q(
                        status__in=("succeeded", "failed", "conflict", "superseded"),
                        generation__isnull=False,
                        finished_at__isnull=False,
                    )
                ),
                name="keyword_generation_status_fields",
            ),
        ]

    def delete(self, *args, **kwargs):
        raise TypeError("Keyword generation jobs cannot be deleted.")


class KeywordGenerationResult(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.OneToOneField(
        KeywordGenerationJob, on_delete=models.PROTECT, related_name="result"
    )
    output_snapshot = models.JSONField()
    output_digest = models.CharField(max_length=64)
    item_count = models.PositiveIntegerField()
    applied_keyword_set_version = models.PositiveBigIntegerField()
    provider_metrics = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = KeywordGenerationImmutableQuerySet.as_manager()

    class Meta:
        db_table = "keyword_generation_results"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(item_count__gte=1)
                & models.Q(applied_keyword_set_version__gte=1)
                & ~models.Q(output_digest=""),
                name="keyword_generation_result_valid",
            )
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Keyword generation results are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Keyword generation results are immutable.")


class KeywordGenerationEvent(models.Model):  # noqa: DJ008
    class EventType(models.TextChoices):
        STARTED = "started", "Started"
        RETRY_SCHEDULED = "retry_scheduled", "Retry scheduled"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CONFLICT = "conflict", "Conflict"
        SUPERSEDED = "superseded", "Superseded"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(KeywordGenerationJob, on_delete=models.PROTECT, related_name="events")
    event_type = models.CharField(max_length=24, choices=EventType.choices)
    stable_error_code = models.CharField(max_length=64, blank=True)
    safe_summary = models.JSONField(default=dict)
    request_id = models.UUIDField(null=True, blank=True)
    correlation_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = KeywordGenerationImmutableQuerySet.as_manager()

    class Meta:
        db_table = "keyword_generation_events"
        ordering = ("job_id", "created_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    event_type__in=(
                        "started",
                        "retry_scheduled",
                        "succeeded",
                        "failed",
                        "conflict",
                        "superseded",
                    )
                ),
                name="keyword_generation_event_type_valid",
            )
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Keyword generation events are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Keyword generation events are immutable.")
