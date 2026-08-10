import uuid

from django.conf import settings
from django.db import models


class SubjectType(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        ACTIVE = "active", "启用"
        INACTIVE = "inactive", "停用"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=500, blank=True)
    icon_key = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    sort_order = models.PositiveIntegerField(default=0)
    is_builtin = models.BooleanField(default=False)
    schema_version = models.PositiveBigIntegerField(default=1)
    version = models.PositiveBigIntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_subject_types",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_subject_types",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "subject_types"
        ordering = ("sort_order", "key", "id")
        indexes = [
            models.Index(fields=("status", "sort_order", "id"), name="subject_type_public_idx")
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=("active", "inactive")),
                name="subject_type_valid_status",
            ),
            models.CheckConstraint(
                condition=models.Q(schema_version__gte=1),
                name="subject_type_schema_version_gte_1",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1), name="subject_type_version_gte_1"
            ),
        ]


class SubjectFieldDefinition(models.Model):  # noqa: DJ008
    class Scope(models.TextChoices):
        COMMON = "common", "公共字段"
        CUSTOM = "custom", "自定义字段"

    class FieldType(models.TextChoices):
        TEXT = "text", "单行文本"
        TEXTAREA = "textarea", "多行文本"
        NUMBER = "number", "数字"
        DATE = "date", "日期"
        SINGLE = "single", "单选"
        MULTI = "multi", "多选"
        SELECT = "select", "下拉选择"
        URL = "url", "网址"
        IMAGE = "image", "图片上传（尚未启用）"
        FILE = "file", "文件上传（尚未启用）"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner_subject_type = models.ForeignKey(
        SubjectType,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="owned_field_definitions",
    )
    field_key = models.CharField(max_length=64)
    field_type = models.CharField(max_length=16, choices=FieldType.choices)
    scope = models.CharField(max_length=16, choices=Scope.choices)
    is_builtin = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_subject_field_definitions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "subject_field_definitions"
        ordering = ("scope", "field_key", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("scope", "owner_subject_type", "field_key"),
                name="subject_field_definition_key_unique",
                nulls_distinct=False,
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(scope="common", owner_subject_type__isnull=True)
                    | models.Q(scope="custom", owner_subject_type__isnull=False)
                ),
                name="subject_field_definition_scope_owner",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    field_type__in=(
                        "text",
                        "textarea",
                        "number",
                        "date",
                        "single",
                        "multi",
                        "select",
                        "url",
                        "image",
                        "file",
                    )
                ),
                name="subject_field_definition_valid_type",
            ),
        ]


class SubjectTypeFieldConfig(models.Model):  # noqa: DJ008
    class NameRole(models.TextChoices):
        NONE = "none", "无"
        OFFICIAL_NAME = "official_name", "正式名称"
        ALIAS = "alias", "别名"
        ENGLISH_NAME = "english_name", "英文名"
        PRODUCT = "product", "产品名称"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subject_type = models.ForeignKey(
        SubjectType, on_delete=models.PROTECT, related_name="field_configs"
    )
    field_definition = models.ForeignKey(
        SubjectFieldDefinition, on_delete=models.PROTECT, related_name="type_configs"
    )
    label = models.CharField(max_length=100)
    description = models.CharField(max_length=500, blank=True)
    required = models.BooleanField(default=False)
    default_value = models.JSONField(null=True, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    enabled = models.BooleanField(default=True)
    used_for_ai = models.BooleanField(default=False)
    name_role = models.CharField(max_length=32, choices=NameRole.choices, default=NameRole.NONE)
    version = models.PositiveBigIntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_subject_field_configs",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_subject_field_configs",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "subject_type_field_configs"
        ordering = ("subject_type_id", "sort_order", "id")
        indexes = [
            models.Index(
                fields=("subject_type", "enabled", "sort_order", "id"),
                name="subject_field_schema_idx",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("subject_type", "field_definition"),
                name="subject_type_field_config_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1), name="subject_field_config_version_gte_1"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    name_role__in=("none", "official_name", "alias", "english_name", "product")
                ),
                name="subject_field_config_valid_name_role",
            ),
            models.CheckConstraint(
                condition=models.Q(enabled=True) | models.Q(required=False),
                name="subject_field_disabled_not_required",
            ),
        ]


class SubjectFieldOption(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    field_config = models.ForeignKey(
        SubjectTypeFieldConfig, on_delete=models.PROTECT, related_name="options"
    )
    option_key = models.CharField(max_length=64)
    label = models.CharField(max_length=100)
    enabled = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    version = models.PositiveBigIntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_subject_field_options",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_subject_field_options",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "subject_field_options"
        ordering = ("field_config_id", "sort_order", "option_key", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("field_config", "option_key"), name="subject_field_option_key_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1), name="subject_field_option_version_gte_1"
            ),
        ]
