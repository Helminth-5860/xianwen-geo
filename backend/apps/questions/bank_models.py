import uuid

from django.conf import settings
from django.db import models

from apps.subjects.models import Subject, SubjectVersion

from .models import QuestionCategory, QuestionTag


class QuestionBankWorkspaceQuerySet(models.QuerySet):
    def delete(self):
        raise TypeError("Question bank workspaces cannot be deleted.")


class QuestionBankImmutableQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError("Question bank history is append-only.")

    def delete(self):
        raise TypeError("Question bank history is append-only.")


class QuestionGenerationJobQuerySet(models.QuerySet):
    def delete(self):
        raise TypeError("Question generation jobs cannot be deleted.")


class QuestionBankWorkspace(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="question_bank_workspaces",
    )
    subject = models.OneToOneField(
        Subject,
        on_delete=models.PROTECT,
        related_name="question_bank_workspace",
    )
    draft_subject_version = models.ForeignKey(
        SubjectVersion,
        on_delete=models.PROTECT,
        related_name="question_bank_drafts",
    )
    draft_distillation_set = models.ForeignKey(
        "keywords.DistillationSet",
        on_delete=models.PROTECT,
        related_name="question_bank_drafts",
    )
    draft_source_result = models.ForeignKey(
        "QuestionGenerationResult",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="applied_workspaces",
    )
    current_version = models.ForeignKey(
        "QuestionBankVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="current_for_workspaces",
    )
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = QuestionBankWorkspaceQuerySet.as_manager()

    class Meta:
        db_table = "question_bank_workspaces"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="question_bank_workspace_version_gte_1",
            )
        ]

    def delete(self, *args, **kwargs):
        raise TypeError("Question bank workspaces cannot be deleted.")


class QuestionFields(models.Model):
    class Priority(models.TextChoices):
        HIGH = "high", "High"
        MEDIUM = "medium", "Medium"
        LOW = "low", "Low"

    class QuestionType(models.TextChoices):
        NATURAL = "natural", "Natural exploration"
        BRAND_DIRECTED = "brand_directed", "Brand directed"

    text = models.CharField(max_length=1000)
    matching_text = models.CharField(max_length=1000, editable=False)
    primary_category = models.ForeignKey(
        QuestionCategory, on_delete=models.PROTECT, related_name="+"
    )
    priority = models.CharField(max_length=16, choices=Priority.choices)
    question_type = models.CharField(max_length=24, choices=QuestionType.choices)
    participates_in_scoring = models.BooleanField(default=True)
    ai_reason = models.CharField(max_length=1000, blank=True)
    tag_ids = models.JSONField(default=list)
    keyword_ids = models.JSONField(default=list)
    sort_order = models.PositiveIntegerField()

    class Meta:
        abstract = True


def question_constraints(prefix):
    return [
        models.CheckConstraint(
            condition=models.Q(priority__in=("high", "medium", "low")),
            name=f"{prefix}_priority_valid",
        ),
        models.CheckConstraint(
            condition=models.Q(question_type__in=("natural", "brand_directed")),
            name=f"{prefix}_type_valid",
        ),
        models.CheckConstraint(
            condition=~models.Q(text="") & ~models.Q(matching_text=""),
            name=f"{prefix}_text_present",
        ),
    ]


class QuestionDraftItem(QuestionFields):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        QuestionBankWorkspace,
        on_delete=models.CASCADE,
        related_name="draft_items",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "question_draft_items"
        ordering = ("workspace_id", "sort_order", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("workspace", "matching_text"),
                name="question_draft_text_unique",
            ),
            models.UniqueConstraint(
                fields=("workspace", "sort_order"),
                name="question_draft_sort_unique",
            ),
            *question_constraints("question_draft"),
        ]


class QuestionBankVersion(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        QuestionBankWorkspace,
        on_delete=models.PROTECT,
        related_name="versions",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="question_bank_versions",
    )
    subject = models.ForeignKey(
        Subject,
        on_delete=models.PROTECT,
        related_name="question_bank_versions",
    )
    subject_version = models.ForeignKey(
        SubjectVersion,
        on_delete=models.PROTECT,
        related_name="question_bank_versions",
    )
    distillation_set = models.ForeignKey(
        "keywords.DistillationSet",
        on_delete=models.PROTECT,
        related_name="question_bank_versions",
    )
    source_result = models.ForeignKey(
        "QuestionGenerationResult",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="confirmed_versions",
    )
    version_no = models.PositiveBigIntegerField()
    content_digest = models.CharField(max_length=64)
    item_count = models.PositiveIntegerField()
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="confirmed_question_bank_versions",
    )
    confirmed_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    objects = QuestionBankImmutableQuerySet.as_manager()

    class Meta:
        db_table = "question_bank_versions"
        ordering = ("workspace_id", "version_no", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("workspace", "version_no"),
                name="question_bank_version_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(version_no__gte=1)
                & models.Q(item_count__gte=1)
                & ~models.Q(content_digest=""),
                name="question_bank_version_valid",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Question bank versions are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Question bank versions are immutable.")


class Question(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question_bank_version = models.ForeignKey(
        QuestionBankVersion,
        on_delete=models.PROTECT,
        related_name="questions",
    )
    text = models.CharField(max_length=1000)
    matching_text = models.CharField(max_length=1000, editable=False)
    primary_category = models.ForeignKey(
        QuestionCategory,
        on_delete=models.PROTECT,
        related_name="questions",
    )
    primary_category_key = models.CharField(max_length=100)
    primary_category_name = models.CharField(max_length=150)
    primary_category_version = models.PositiveBigIntegerField()
    priority = models.CharField(max_length=16, choices=QuestionFields.Priority.choices)
    question_type = models.CharField(max_length=24, choices=QuestionFields.QuestionType.choices)
    participates_in_scoring = models.BooleanField(default=True)
    ai_reason = models.CharField(max_length=1000, blank=True)
    sort_order = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    objects = QuestionBankImmutableQuerySet.as_manager()

    class Meta:
        db_table = "questions"
        ordering = ("question_bank_version_id", "sort_order", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("question_bank_version", "matching_text"),
                name="question_text_unique",
            ),
            models.UniqueConstraint(
                fields=("question_bank_version", "sort_order"),
                name="question_sort_unique",
            ),
            *question_constraints("question"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Questions are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Questions are immutable.")


class QuestionTagLink(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name="tag_links")
    tag = models.ForeignKey(QuestionTag, on_delete=models.PROTECT, related_name="question_links")
    tag_key = models.CharField(max_length=100)
    tag_name = models.CharField(max_length=150)
    tag_version = models.PositiveBigIntegerField()

    objects = QuestionBankImmutableQuerySet.as_manager()

    class Meta:
        db_table = "question_tag_links"
        constraints = [
            models.UniqueConstraint(fields=("question", "tag"), name="question_tag_link_unique")
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Question tag links are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Question tag links are immutable.")


class QuestionKeywordLink(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name="keyword_links")
    keyword = models.ForeignKey(
        "keywords.Keyword",
        on_delete=models.PROTECT,
        related_name="question_links",
    )
    keyword_text = models.CharField(max_length=500)

    objects = QuestionBankImmutableQuerySet.as_manager()

    class Meta:
        db_table = "question_keyword_links"
        constraints = [
            models.UniqueConstraint(
                fields=("question", "keyword"),
                name="question_keyword_link_unique",
            )
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Question keyword links are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Question keyword links are immutable.")


class QuestionGenerationJob(models.Model):  # noqa: DJ008
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
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="question_generation_jobs",
    )
    subject = models.ForeignKey(
        Subject,
        on_delete=models.PROTECT,
        related_name="question_generation_jobs",
    )
    subject_version = models.ForeignKey(
        SubjectVersion,
        on_delete=models.PROTECT,
        related_name="question_generation_jobs",
    )
    input_distillation_set = models.ForeignKey(
        "keywords.DistillationSet",
        on_delete=models.PROTECT,
        related_name="question_generation_jobs",
    )
    subscription = models.ForeignKey(
        "plans.Subscription",
        on_delete=models.PROTECT,
        related_name="question_generation_jobs",
    )
    quota_hold = models.ForeignKey(
        "quotas.QuotaHoldGroup",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="question_generation_jobs",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    billing_mode = models.CharField(max_length=16, choices=BillingMode.choices)
    version = models.PositiveBigIntegerField(default=1)
    expected_workspace_version = models.PositiveBigIntegerField()
    question_limit = models.PositiveIntegerField()
    input_subject_values = models.JSONField(default=dict)
    input_keywords = models.JSONField(default=list)
    input_categories = models.JSONField(default=list)
    input_tags = models.JSONField(default=list)
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

    objects = QuestionGenerationJobQuerySet.as_manager()

    class Meta:
        db_table = "question_generation_jobs"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(
                fields=("subject", "status", "created_at"),
                name="question_gen_status_idx",
            ),
            models.Index(
                fields=("status", "next_attempt_at"),
                name="question_gen_retry_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("subject",),
                condition=models.Q(status__in=("queued", "running", "retry_wait")),
                name="question_generation_one_open",
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
                name="question_generation_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(billing_mode="free_initial", quota_hold__isnull=True)
                | models.Q(billing_mode="regeneration", quota_hold__isnull=False),
                name="question_generation_billing_hold",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1) & models.Q(question_limit__gte=1),
                name="question_generation_counts_valid",
            ),
        ]

    def delete(self, *args, **kwargs):
        raise TypeError("Question generation jobs cannot be deleted.")


class QuestionGenerationResult(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.OneToOneField(
        QuestionGenerationJob,
        on_delete=models.PROTECT,
        related_name="result",
    )
    output_snapshot = models.JSONField()
    output_digest = models.CharField(max_length=64)
    item_count = models.PositiveIntegerField()
    applied_workspace_version = models.PositiveBigIntegerField()
    provider_metrics = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = QuestionBankImmutableQuerySet.as_manager()

    class Meta:
        db_table = "question_generation_results"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(item_count__gte=1)
                & models.Q(applied_workspace_version__gte=1)
                & ~models.Q(output_digest=""),
                name="question_generation_result_valid",
            )
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Question generation results are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Question generation results are immutable.")


class QuestionGenerationEvent(models.Model):  # noqa: DJ008
    class EventType(models.TextChoices):
        STARTED = "started", "Started"
        RETRY_SCHEDULED = "retry_scheduled", "Retry scheduled"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CONFLICT = "conflict", "Conflict"
        SUPERSEDED = "superseded", "Superseded"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(
        QuestionGenerationJob,
        on_delete=models.PROTECT,
        related_name="events",
    )
    event_type = models.CharField(max_length=24, choices=EventType.choices)
    stable_error_code = models.CharField(max_length=64, blank=True)
    safe_summary = models.JSONField(default=dict)
    request_id = models.UUIDField(null=True, blank=True)
    correlation_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = QuestionBankImmutableQuerySet.as_manager()

    class Meta:
        db_table = "question_generation_events"
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
                name="question_generation_event_valid",
            )
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Question generation events are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Question generation events are immutable.")
