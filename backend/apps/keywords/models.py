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

    text = models.CharField(max_length=500)
    matching_text = models.CharField(max_length=500)
    structure_type = models.CharField(max_length=16, choices=StructureType.choices)
    is_regional = models.BooleanField(default=False)
    region_level = models.CharField(max_length=16, choices=RegionLevel.choices, blank=True)
    region_text = models.CharField(max_length=200, blank=True)
    region_matching_key = models.CharField(max_length=240, blank=True)
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
