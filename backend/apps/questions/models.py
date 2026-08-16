import uuid

from django.conf import settings
from django.db import models

from apps.subjects.models import SubjectType


class QuestionCatalogBase(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "启用"
        INACTIVE = "inactive", "停用"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=150)
    normalized_name = models.CharField(max_length=150, unique=True, editable=False)
    description = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    sort_order = models.PositiveIntegerField(default=0)
    is_builtin = models.BooleanField(default=False)
    version = models.PositiveBigIntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_%(class)ss",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_%(class)ss",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class QuestionCategory(QuestionCatalogBase):  # noqa: DJ008
    generation_guidance = models.CharField(max_length=2000, blank=True)
    applicable_subject_types = models.ManyToManyField(  # type: ignore[var-annotated]
        SubjectType,
        through="QuestionCategorySubjectType",
        related_name="question_categories",
    )

    class Meta:
        db_table = "question_categories"
        ordering = ("sort_order", "key", "id")
        indexes = [
            models.Index(fields=("status", "sort_order", "id"), name="question_category_public_idx")
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=("active", "inactive")),
                name="question_category_valid_status",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1), name="question_category_version_gte_1"
            ),
        ]


class QuestionCategorySubjectType(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.ForeignKey(
        QuestionCategory, on_delete=models.CASCADE, related_name="subject_type_links"
    )
    subject_type = models.ForeignKey(
        SubjectType, on_delete=models.PROTECT, related_name="question_category_links"
    )

    class Meta:
        db_table = "question_category_subject_types"
        constraints = [
            models.UniqueConstraint(
                fields=("category", "subject_type"),
                name="question_category_subject_type_unique",
            )
        ]


class QuestionTag(QuestionCatalogBase):  # noqa: DJ008
    applicable_subject_types = models.ManyToManyField(  # type: ignore[var-annotated]
        SubjectType,
        through="QuestionTagSubjectType",
        related_name="question_tags",
    )

    class Meta:
        db_table = "question_tags"
        ordering = ("sort_order", "key", "id")
        indexes = [
            models.Index(fields=("status", "sort_order", "id"), name="question_tag_public_idx")
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=("active", "inactive")),
                name="question_tag_valid_status",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1), name="question_tag_version_gte_1"
            ),
        ]


class QuestionTagSubjectType(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tag = models.ForeignKey(
        QuestionTag, on_delete=models.CASCADE, related_name="subject_type_links"
    )
    subject_type = models.ForeignKey(
        SubjectType, on_delete=models.PROTECT, related_name="question_tag_links"
    )

    class Meta:
        db_table = "question_tag_subject_types"
        constraints = [
            models.UniqueConstraint(
                fields=("tag", "subject_type"), name="question_tag_subject_type_unique"
            )
        ]
