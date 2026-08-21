from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class ImmutableQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError("Immutable content evidence cannot be updated.")

    def delete(self):
        raise TypeError("Immutable content evidence cannot be deleted.")


class ArticleType(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        DISABLED = "disabled", "Disabled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    applicable_subject_types = models.JSONField(default=list)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "article_types"
        ordering = ("sort_order", "key")


class ArticleTemplateVersion(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    article_type = models.ForeignKey(ArticleType, on_delete=models.PROTECT, related_name="versions")
    version_no = models.PositiveIntegerField()
    prompt_version = models.CharField(max_length=64)
    structure = models.JSONField(default=dict)
    network_policy = models.CharField(max_length=24, default="optional")
    citation_required = models.BooleanField(default=True)
    allowed_source_types = models.JSONField(default=list)
    recommended_channel_keys = models.JSONField(default=list)
    is_current = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableQuerySet.as_manager()

    class Meta:
        db_table = "article_template_versions"
        constraints = [
            models.UniqueConstraint(
                fields=("article_type", "version_no"), name="article_tpl_ver_unique"
            ),
            models.UniqueConstraint(
                fields=("article_type",),
                condition=Q(is_current=True),
                name="article_tpl_one_current",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Article template versions are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Article template versions are immutable.")


class ArticleSourcePack(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        CONFIRMED = "confirmed", "Confirmed"

    class ConflictStatus(models.TextChoices):
        CLEAR = "clear", "Clear"
        PENDING = "pending", "Pending"
        RESOLVED = "resolved", "Resolved"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    subject = models.ForeignKey(
        "subjects.Subject", on_delete=models.PROTECT, related_name="article_source_packs"
    )
    subject_version = models.ForeignKey("subjects.SubjectVersion", on_delete=models.PROTECT)
    article_type = models.ForeignKey(ArticleType, on_delete=models.PROTECT)
    template_version = models.ForeignKey(ArticleTemplateVersion, on_delete=models.PROTECT)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    conflict_status = models.CharField(
        max_length=16, choices=ConflictStatus.choices, default=ConflictStatus.CLEAR
    )
    conflicts = models.JSONField(default=list)
    frozen_snapshot = models.JSONField(default=dict)
    snapshot_digest = models.CharField(max_length=64, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "article_source_packs"
        ordering = ("-created_at", "-id")


class ArticleSourceItem(models.Model):  # noqa: DJ008
    class SourceType(models.TextChoices):
        SUBJECT = "subject", "Subject data"
        DOCUMENT = "document", "Confirmed document"
        WEB = "web", "Confirmed web page"

    class Verification(models.TextChoices):
        VERIFIED = "verified", "Verified"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_pack = models.ForeignKey(
        ArticleSourcePack, on_delete=models.PROTECT, related_name="items"
    )
    source_type = models.CharField(max_length=16, choices=SourceType.choices)
    document_parsed_version = models.ForeignKey(
        "documents.DocumentParsedVersion", null=True, blank=True, on_delete=models.PROTECT
    )
    web_source_version = models.ForeignKey(
        "web_sources.WebSourceParsedVersion", null=True, blank=True, on_delete=models.PROTECT
    )
    title = models.CharField(max_length=500)
    url = models.TextField(blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    trust_level = models.PositiveSmallIntegerField(default=100)
    verification_status = models.CharField(
        max_length=16, choices=Verification.choices, default=Verification.VERIFIED
    )
    excerpt = models.TextField()
    content_digest = models.CharField(max_length=64)
    user_confirmed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "article_source_items"
        constraints = [
            models.CheckConstraint(
                condition=Q(trust_level__gte=0, trust_level__lte=100),
                name="article_source_trust_range",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        source_type="subject",
                        document_parsed_version__isnull=True,
                        web_source_version__isnull=True,
                    )
                    | Q(
                        source_type="document",
                        document_parsed_version__isnull=False,
                        web_source_version__isnull=True,
                    )
                    | Q(
                        source_type="web",
                        document_parsed_version__isnull=True,
                        web_source_version__isnull=False,
                    )
                ),
                name="article_source_reference_valid",
            ),
        ]


class Article(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        GENERATING = "generating", "Generating"
        REVIEWING = "reviewing", "Reviewing"
        READY = "ready", "Ready"
        REJECTED = "rejected", "Rejected"

    class Depth(models.TextChoices):
        CONCISE = "concise", "Concise"
        STANDARD = "standard", "Standard"
        DEEP = "deep", "Deep"

    class Moderation(models.TextChoices):
        NOT_CHECKED = "not_checked", "Not checked"
        PASSED = "passed", "Passed"
        MANUAL_REVIEW = "manual_review", "Manual review"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="articles"
    )
    subject = models.ForeignKey(
        "subjects.Subject", on_delete=models.PROTECT, related_name="articles"
    )
    subject_version = models.ForeignKey("subjects.SubjectVersion", on_delete=models.PROTECT)
    article_type = models.ForeignKey(ArticleType, null=True, blank=True, on_delete=models.PROTECT)
    template_version = models.ForeignKey(
        ArticleTemplateVersion, null=True, blank=True, on_delete=models.PROTECT
    )
    custom_type = models.CharField(max_length=100, blank=True)
    title = models.CharField(max_length=500, blank=True)
    content = models.TextField(blank=True)
    ai_original_title = models.CharField(max_length=500, blank=True)
    ai_original_content = models.TextField(blank=True)
    ai_citations = models.JSONField(default=list)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    content_depth = models.CharField(max_length=16, choices=Depth.choices, default=Depth.STANDARD)
    source_pack = models.ForeignKey(
        ArticleSourcePack, null=True, blank=True, on_delete=models.PROTECT, related_name="articles"
    )
    current_quality_score = models.PositiveSmallIntegerField(null=True, blank=True)
    moderation_status = models.CharField(
        max_length=24, choices=Moderation.choices, default=Moderation.NOT_CHECKED
    )
    version = models.PositiveBigIntegerField(default=1)
    autosaved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "articles"
        ordering = ("-updated_at", "-id")
        constraints = [
            models.CheckConstraint(condition=Q(version__gte=1), name="article_version_gte_1"),
            models.CheckConstraint(
                condition=Q(current_quality_score__isnull=True) | Q(current_quality_score__lte=100),
                name="article_quality_range",
            ),
            models.CheckConstraint(
                condition=(
                    Q(article_type__isnull=False, template_version__isnull=False, custom_type="")
                    | Q(article_type__isnull=True, template_version__isnull=True)
                    & ~Q(custom_type="")
                ),
                name="article_type_binding_valid",
            ),
        ]


class ArticleOutline(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        EMPTY = "empty", "Empty"
        GENERATING = "generating", "Generating"
        READY = "ready", "Ready"
        CONFIRMED = "confirmed", "Confirmed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    article = models.OneToOneField(Article, on_delete=models.PROTECT, related_name="outline")
    text = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.EMPTY)
    generation_count = models.PositiveIntegerField(default=0)
    first_generation_free = models.BooleanField(default=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveBigIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "article_outlines"
        constraints = [
            models.CheckConstraint(
                condition=Q(version__gte=1), name="article_outline_version_gte_1"
            )
        ]


class ArticleGenerationJob(models.Model):  # noqa: DJ008
    class Operation(models.TextChoices):
        OUTLINE = "outline", "Outline"
        BODY = "body", "Body"
        QUALITY = "quality", "Quality"
        LOCAL_OPTIMIZE = "local_optimize", "Local optimize"
        FULL_OPTIMIZE = "full_optimize", "Full optimize"
        CHANNEL_ADAPT = "channel_adapt", "Channel adapt"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    article = models.ForeignKey(Article, on_delete=models.PROTECT, related_name="generation_jobs")
    operation = models.CharField(max_length=24, choices=Operation.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    subscription = models.ForeignKey("plans.Subscription", on_delete=models.PROTECT)
    quota_hold = models.ForeignKey(
        "quotas.QuotaHoldGroup", null=True, blank=True, on_delete=models.PROTECT
    )
    source_pack_snapshot = models.JSONField(default=dict)
    source_pack_digest = models.CharField(max_length=64)
    input_snapshot = models.JSONField(default=dict)
    input_digest = models.CharField(max_length=64)
    provider_key = models.CharField(max_length=64, default="deepseek")
    model_key = models.CharField(max_length=64, default="deepseek")
    provider_model_id = models.CharField(max_length=255)
    adapter_version = models.CharField(max_length=64)
    prompt_version = models.CharField(max_length=64)
    schema_version = models.CharField(max_length=64)
    idempotency_key_digest = models.CharField(max_length=64, unique=True)
    request_digest = models.CharField(max_length=64)
    request_id = models.UUIDField(null=True, blank=True)
    generation = models.UUIDField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    output_digest = models.CharField(max_length=64, blank=True)
    usage_summary = models.JSONField(default=dict)
    safe_error_code = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "article_generation_jobs"
        ordering = ("-created_at", "-id")
        indexes = [models.Index(fields=("status", "created_at"), name="article_job_status_idx")]

    def delete(self, *args, **kwargs):
        raise TypeError("Article generation evidence cannot be deleted.")


class ArticleComparisonCandidate(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CHOSEN = "chosen", "Chosen"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    article = models.ForeignKey(Article, on_delete=models.PROTECT, related_name="comparisons")
    job = models.OneToOneField(ArticleGenerationJob, on_delete=models.PROTECT)
    original_title = models.CharField(max_length=500)
    original_content = models.TextField()
    optimized_title = models.CharField(max_length=500)
    optimized_content = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    choice = models.CharField(max_length=16, blank=True)
    expires_at = models.DateTimeField()
    chosen_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "article_comparison_candidates"


class ArticleGenerationResult(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.OneToOneField(
        ArticleGenerationJob, on_delete=models.PROTECT, related_name="result"
    )
    normalized_output = models.JSONField()
    output_digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableQuerySet.as_manager()

    class Meta:
        db_table = "article_generation_results"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Article generation results are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Article generation results are immutable.")


class ArticleQualityCheck(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    article = models.ForeignKey(Article, on_delete=models.PROTECT, related_name="quality_checks")
    job = models.OneToOneField(
        ArticleGenerationJob, null=True, blank=True, on_delete=models.PROTECT
    )
    total_score = models.PositiveSmallIntegerField()
    subject_consistency = models.PositiveSmallIntegerField()
    factual_reliability = models.PositiveSmallIntegerField()
    topic_relevance = models.PositiveSmallIntegerField()
    structural_completeness = models.PositiveSmallIntegerField()
    readability = models.PositiveSmallIntegerField()
    keyword_naturalness = models.PositiveSmallIntegerField()
    suggestions = models.JSONField(default=list)
    rule_version = models.CharField(max_length=64, default="article-quality-v1")
    first_free = models.BooleanField(default=False)
    content_digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableQuerySet.as_manager()

    class Meta:
        db_table = "article_quality_checks"
        ordering = ("-created_at", "-id")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Article quality evidence is immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Article quality evidence is immutable.")


class ArticleModerationReview(models.Model):  # noqa: DJ008
    class Kind(models.TextChoices):
        AUTOMATIC = "automatic", "Automatic"
        MANUAL = "manual", "Manual"
        APPEAL = "appeal", "Appeal"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    article = models.ForeignKey(
        Article, on_delete=models.PROTECT, related_name="moderation_reviews"
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    result = models.CharField(max_length=24)
    responsibility = models.CharField(max_length=24, blank=True)
    safe_reason_code = models.CharField(max_length=100, blank=True)
    review_no = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableQuerySet.as_manager()

    class Meta:
        db_table = "article_moderation_reviews"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Moderation evidence is immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Moderation evidence is immutable.")


class ArticleExport(models.Model):  # noqa: DJ008
    class Format(models.TextChoices):
        WORD = "word", "Word"
        PDF = "pdf", "PDF"
        TXT = "txt", "TXT"
        MARKDOWN = "markdown", "Markdown"
        HTML = "html", "HTML"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    article = models.ForeignKey(Article, on_delete=models.PROTECT, related_name="exports")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    format = models.CharField(max_length=16, choices=Format.choices)
    object_key = models.CharField(max_length=500)
    content_digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableQuerySet.as_manager()

    class Meta:
        db_table = "article_exports"
        ordering = ("-created_at", "-id")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Article export evidence is immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Article export evidence is immutable.")


class PublishingChannel(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=100)
    logo_url = models.TextField(blank=True)
    official_url = models.TextField()
    channel_type = models.CharField(max_length=32)
    description = models.TextField(blank=True)
    applicable_article_types = models.JSONField(default=list)
    image_ratios = models.JSONField(default=list)
    enabled = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "publishing_channels"
        ordering = ("sort_order", "key")


class ChannelTemplateVersion(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    channel = models.ForeignKey(
        PublishingChannel, on_delete=models.PROTECT, related_name="versions"
    )
    version_no = models.PositiveIntegerField()
    rules = models.JSONField(default=dict)
    prompt_version = models.CharField(max_length=64)
    is_current = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableQuerySet.as_manager()

    class Meta:
        db_table = "channel_template_versions"
        constraints = [
            models.UniqueConstraint(
                fields=("channel", "version_no"), name="channel_tpl_ver_unique"
            ),
            models.UniqueConstraint(
                fields=("channel",), condition=Q(is_current=True), name="channel_tpl_one_current"
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Channel template versions are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Channel template versions are immutable.")


class ChannelAdaptation(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    article = models.ForeignKey(
        Article, on_delete=models.PROTECT, related_name="channel_adaptations"
    )
    channel = models.ForeignKey(PublishingChannel, on_delete=models.PROTECT)
    template_version = models.ForeignKey(ChannelTemplateVersion, on_delete=models.PROTECT)
    job = models.OneToOneField(
        ArticleGenerationJob, null=True, blank=True, on_delete=models.PROTECT
    )
    title = models.CharField(max_length=500, blank=True)
    content = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    quality_score = models.PositiveSmallIntegerField(null=True, blank=True)
    safe_error_code = models.CharField(max_length=100, blank=True)
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "channel_adaptations"
        ordering = ("-created_at", "-id")
        constraints = [
            models.CheckConstraint(
                condition=Q(version__gte=1), name="channel_adaptation_version_gte_1"
            )
        ]


class PublicationLinkCheck(models.Model):  # noqa: DJ008
    class Result(models.TextChoices):
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        UNKNOWN = "unknown", "Unknown"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    subject = models.ForeignKey(
        "subjects.Subject", on_delete=models.PROTECT, related_name="publication_checks"
    )
    article = models.ForeignKey(Article, null=True, blank=True, on_delete=models.PROTECT)
    adaptation = models.ForeignKey(
        ChannelAdaptation, null=True, blank=True, on_delete=models.PROTECT
    )
    channel = models.ForeignKey(PublishingChannel, on_delete=models.PROTECT)
    url = models.TextField()
    result = models.CharField(max_length=16, choices=Result.choices)
    detected_title = models.CharField(max_length=500, blank=True)
    match_summary = models.CharField(max_length=1000, blank=True)
    safe_failure_code = models.CharField(max_length=100, blank=True)
    checked_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableQuerySet.as_manager()

    class Meta:
        db_table = "publication_link_checks"
        ordering = ("-checked_at", "-id")
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(article__isnull=False, adaptation__isnull=True)
                    | Q(article__isnull=True, adaptation__isnull=False)
                ),
                name="publication_check_target_valid",
            )
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Publication checks are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Publication checks are immutable.")
