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


class SubjectQuerySet(models.QuerySet):
    def delete(self):
        raise TypeError("Subjects cannot be deleted.")


class Subject(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        DRAFT = "draft", "\u8349\u7a3f"
        ACTIVE = "active", "\u542f\u7528"
        ARCHIVED = "archived", "\u5df2\u5f52\u6863"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="subjects",
    )
    subject_type = models.ForeignKey(
        SubjectType,
        on_delete=models.PROTECT,
        related_name="subjects",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    draft_values = models.JSONField(default=dict)
    schema_version = models.PositiveBigIntegerField()
    schema_snapshot_format_version = models.PositiveSmallIntegerField(default=1)
    schema_snapshot = models.JSONField()
    schema_digest = models.CharField(max_length=64)
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SubjectQuerySet.as_manager()

    class Meta:
        db_table = "subjects"
        ordering = ("-updated_at", "id")
        indexes = [
            models.Index(fields=("user", "status", "created_at"), name="subject_user_status_idx"),
            models.Index(
                fields=("subject_type", "status", "created_at"),
                name="subject_type_status_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=("draft", "active", "archived")),
                name="subject_valid_status",
            ),
            models.CheckConstraint(
                condition=models.Q(schema_version__gte=1),
                name="subject_schema_version_gte_1",
            ),
            models.CheckConstraint(
                condition=models.Q(schema_snapshot_format_version=1),
                name="subject_schema_format_v1",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="subject_version_gte_1",
            ),
        ]


class AppendOnlySubjectVersionQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError("Subject versions are append-only.")

    def delete(self):
        raise TypeError("Subject versions are append-only.")


class SubjectVersion(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="versions")
    version_no = models.PositiveBigIntegerField()
    field_values = models.JSONField()
    schema_version = models.PositiveBigIntegerField()
    schema_snapshot_format_version = models.PositiveSmallIntegerField(default=1)
    schema_snapshot = models.JSONField()
    schema_digest = models.CharField(max_length=64)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_subject_versions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlySubjectVersionQuerySet.as_manager()

    class Meta:
        db_table = "subject_versions"
        ordering = ("subject_id", "version_no", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("subject", "version_no"),
                name="subject_version_number_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(version_no__gte=1),
                name="subject_version_number_gte_1",
            ),
            models.CheckConstraint(
                condition=models.Q(schema_version__gte=1),
                name="subject_version_schema_gte_1",
            ),
            models.CheckConstraint(
                condition=models.Q(schema_snapshot_format_version=1),
                name="subject_version_schema_format_v1",
            ),
        ]


class AppendOnlySubjectEventQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError("Subject events are append-only.")

    def delete(self):
        raise TypeError("Subject events are append-only.")


class SubjectEvent(models.Model):  # noqa: DJ008
    class EventType(models.TextChoices):
        CREATED = "created", "\u5df2\u521b\u5efa"
        ACTIVATED = "activated", "\u5df2\u542f\u7528"
        ARCHIVED = "archived", "\u5df2\u5f52\u6863"
        CURRENT_SELECTED = "current_selected", "\u5df2\u8bbe\u4e3a\u5f53\u524d\u4e3b\u4f53"
        CURRENT_CLEARED = "current_cleared", "\u5df2\u6e05\u9664\u5f53\u524d\u4e3b\u4f53"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="events")
    event_type = models.CharField(max_length=32, choices=EventType.choices)
    from_status = models.CharField(max_length=16, blank=True)
    to_status = models.CharField(max_length=16, choices=Subject.Status.choices)
    safe_summary = models.JSONField(default=dict)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="performed_subject_events",
    )
    request_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlySubjectEventQuerySet.as_manager()

    class Meta:
        db_table = "subject_events"
        ordering = ("subject_id", "created_at", "id")
        indexes = [models.Index(fields=("subject", "created_at"), name="subject_event_created_idx")]


class SubjectContextQuerySet(models.QuerySet):
    def delete(self):
        raise TypeError("Subject contexts cannot be deleted.")


class SubjectContext(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="subject_context",
    )
    current_subject = models.ForeignKey(
        Subject,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="selected_by_contexts",
    )
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SubjectContextQuerySet.as_manager()

    class Meta:
        db_table = "subject_contexts"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="subject_context_version_gte_1",
            )
        ]
