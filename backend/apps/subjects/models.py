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
    tenant = models.ForeignKey(
        "users.Tenant",
        null=True,
        blank=True,
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
    current_version = models.ForeignKey(
        "SubjectVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="current_for_subjects",
    )
    identity_bound_at = models.DateTimeField(null=True, blank=True)
    bound_official_name = models.CharField(max_length=500, blank=True)
    bound_unified_social_credit_code = models.CharField(max_length=32, blank=True)
    retest_required = models.BooleanField(default=False)
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
                fields=("tenant", "status", "created_at"), name="subject_tenant_status_idx"
            ),
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
            models.UniqueConstraint(
                fields=("tenant",),
                condition=models.Q(status="active", tenant__isnull=False),
                name="subject_one_active_per_tenant",
            ),
            models.UniqueConstraint(
                fields=("user",),
                condition=models.Q(status="active", tenant__isnull=True),
                name="subject_one_active_per_user_workspace",
            ),
        ]


class SubjectBusinessProfile(models.Model):  # noqa: DJ008
    class LegalEntityType(models.TextChoices):
        COMPANY = "company", "公司"
        INDIVIDUAL_BUSINESS = "individual_business", "个体工商户"

    subject = models.OneToOneField(
        Subject,
        primary_key=True,
        on_delete=models.CASCADE,
        related_name="business_profile",
    )
    legal_entity_type = models.CharField(max_length=32, choices=LegalEntityType.choices)
    contact_name = models.CharField(max_length=100, blank=True)
    contact_phone = models.CharField(max_length=32, blank=True)
    business_address = models.CharField(max_length=500)
    industry = models.CharField(max_length=200, blank=True)
    primary_business = models.TextField()
    brand_name = models.CharField(max_length=200, blank=True)
    subject_aliases = models.TextField(blank=True)
    unified_social_credit_code = models.CharField(max_length=32, blank=True)
    social_channels = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "subject_business_profiles"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(legal_entity_type__in=("company", "individual_business")),
                name="subject_profile_valid_entity_type",
            )
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
    field_values_digest = models.CharField(max_length=64)
    semantic_digest = models.CharField(max_length=64)
    official_name = models.CharField(max_length=500)
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


class AppendOnlySubjectSemanticQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError("Subject version semantics are append-only.")

    def delete(self):
        raise TypeError("Subject version semantics are append-only.")


class SubjectName(models.Model):  # noqa: DJ008
    class Role(models.TextChoices):
        OFFICIAL_NAME = "official_name", "\u6b63\u5f0f\u540d\u79f0"
        ALIAS = "alias", "\u522b\u540d"
        ENGLISH_NAME = "english_name", "\u82f1\u6587\u540d"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subject_version = models.ForeignKey(
        SubjectVersion,
        on_delete=models.PROTECT,
        related_name="names",
    )
    role = models.CharField(max_length=32, choices=Role.choices)
    display_value = models.CharField(max_length=500)
    matching_value = models.CharField(max_length=500)
    source_field_key = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlySubjectSemanticQuerySet.as_manager()

    class Meta:
        db_table = "subject_names"
        ordering = ("subject_version_id", "role", "display_value", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("subject_version", "role", "matching_value"),
                name="subject_name_version_role_value_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(role__in=("official_name", "alias", "english_name")),
                name="subject_name_valid_role",
            ),
        ]


class SubjectProduct(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subject_version = models.ForeignKey(
        SubjectVersion,
        on_delete=models.PROTECT,
        related_name="products",
    )
    candidate_key = models.CharField(max_length=64)
    display_value = models.CharField(max_length=500)
    matching_value = models.CharField(max_length=500)
    source_field_key = models.CharField(max_length=64)
    uniqueness_confirmed = models.BooleanField(default=False)
    include_in_mention = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlySubjectSemanticQuerySet.as_manager()

    class Meta:
        db_table = "subject_products"
        ordering = ("subject_version_id", "display_value", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("subject_version", "candidate_key"),
                name="subject_product_candidate_unique",
            ),
            models.UniqueConstraint(
                fields=("subject_version", "matching_value"),
                name="subject_product_value_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(include_in_mention=False) | models.Q(uniqueness_confirmed=True),
                name="subject_product_mention_requires_unique",
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
        VERSION_COMMITTED = "version_committed", "\u5df2\u63d0\u4ea4\u6b63\u5f0f\u7248\u672c"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="events")
    subject_version = models.ForeignKey(
        SubjectVersion,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="events",
    )
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


class SubjectIdentityCorrectionEvent(models.Model):  # noqa: DJ008
    """Append-only audit record reserved for privileged identity corrections."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subject = models.ForeignKey(
        Subject,
        on_delete=models.PROTECT,
        related_name="identity_correction_events",
    )
    old_identity = models.JSONField()
    new_identity = models.JSONField()
    reason = models.TextField()
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="subject_identity_corrections",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlySubjectEventQuerySet.as_manager()

    class Meta:
        db_table = "subject_identity_correction_events"
        ordering = ("subject_id", "created_at", "id")
        indexes = [
            models.Index(fields=("subject", "created_at"), name="subject_identity_audit_idx")
        ]


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


class SubjectRiskCatalogState(models.Model):  # noqa: DJ008
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    version = models.PositiveBigIntegerField(default=1)
    published_revision = models.OneToOneField(
        "SubjectRiskCatalogRevision",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="published_for_state",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "subject_risk_catalog_state"
        constraints = [
            models.CheckConstraint(condition=models.Q(id=1), name="subject_risk_state_singleton"),
            models.CheckConstraint(
                condition=models.Q(version__gte=1), name="subject_risk_state_version_gte_1"
            ),
        ]


class SubjectRiskType(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=500, blank=True)
    enabled = models.BooleanField(default=False)
    manual_review_required = models.BooleanField(default=True)
    allow_geo_detection = models.BooleanField(default=False)
    allow_article_generation = models.BooleanField(default=False)
    allow_image_generation = models.BooleanField(default=False)
    require_authoritative_citations = models.BooleanField(default=True)
    require_disclaimer = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    version = models.PositiveBigIntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_subject_risk_types",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_subject_risk_types",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "subject_risk_types"
        ordering = ("sort_order", "key", "id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(version__gte=1), name="subject_risk_type_version_gte_1"
            )
        ]


class SubjectRiskRule(models.Model):  # noqa: DJ008
    class Operator(models.TextChoices):
        EQUALS_ANY = "equals_any", "\u7b49\u4e8e\u4efb\u4e00\u503c"
        CONTAINS_ANY = "contains_any", "\u5305\u542b\u4efb\u4e00\u503c"

    class ReasonType(models.TextChoices):
        SUSPECTED_VIOLATION = "suspected_violation", "\u7591\u4f3c\u8fdd\u89c4"
        SUSPECTED_IMPERSONATION = "suspected_impersonation", "\u7591\u4f3c\u5192\u7528"
        DATA_CONFLICT = "data_conflict", "\u8d44\u6599\u51b2\u7a81"
        HIGH_RISK_INDUSTRY = "high_risk_industry", "\u9ad8\u98ce\u9669\u884c\u4e1a"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(max_length=64, unique=True)
    risk_type = models.ForeignKey(
        SubjectRiskType,
        on_delete=models.PROTECT,
        related_name="rules",
    )
    subject_type = models.ForeignKey(
        SubjectType,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="risk_rules",
    )
    field_key = models.CharField(max_length=64, blank=True)
    operator = models.CharField(max_length=16, choices=Operator.choices)
    patterns = models.JSONField(default=list)
    reason_type = models.CharField(max_length=32, choices=ReasonType.choices)
    enabled = models.BooleanField(default=False)
    priority = models.PositiveIntegerField(default=0)
    version = models.PositiveBigIntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_subject_risk_rules",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_subject_risk_rules",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "subject_risk_rules"
        ordering = ("priority", "key", "id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(operator__in=("equals_any", "contains_any")),
                name="subject_risk_rule_valid_operator",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    reason_type__in=(
                        "suspected_violation",
                        "suspected_impersonation",
                        "data_conflict",
                        "high_risk_industry",
                    )
                ),
                name="subject_risk_rule_valid_reason",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1), name="subject_risk_rule_version_gte_1"
            ),
        ]


class AppendOnlySubjectRiskQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError("Subject risk evidence is append-only.")

    def delete(self):
        raise TypeError("Subject risk evidence is append-only.")


class SubjectRiskCatalogRevision(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    revision_no = models.PositiveBigIntegerField(unique=True)
    draft_version = models.PositiveBigIntegerField()
    format_version = models.PositiveSmallIntegerField(default=1)
    snapshot = models.JSONField()
    snapshot_digest = models.CharField(max_length=64, unique=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="published_subject_risk_revisions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlySubjectRiskQuerySet.as_manager()

    class Meta:
        db_table = "subject_risk_catalog_revisions"
        ordering = ("-revision_no", "id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(revision_no__gte=1),
                name="subject_risk_revision_no_gte_1",
            ),
            models.CheckConstraint(
                condition=models.Q(draft_version__gte=1),
                name="subject_risk_revision_draft_version_gte_1",
            ),
            models.CheckConstraint(
                condition=models.Q(format_version=1), name="subject_risk_revision_format_v1"
            ),
        ]


class SubjectRiskAssessment(models.Model):  # noqa: DJ008
    class Outcome(models.TextChoices):
        CLEAR = "clear", "\u81ea\u52a8\u68c0\u67e5\u901a\u8fc7"
        RESTRICTED = "restricted", "\u81ea\u52a8\u9650\u5236"
        REVIEW_REQUIRED = "review_required", "\u9700\u8981\u4eba\u5de5\u5ba1\u6838"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subject_version = models.OneToOneField(
        SubjectVersion,
        on_delete=models.PROTECT,
        related_name="risk_assessment",
    )
    catalog_revision = models.ForeignKey(
        SubjectRiskCatalogRevision,
        on_delete=models.PROTECT,
        related_name="assessments",
    )
    semantic_digest = models.CharField(max_length=64)
    outcome = models.CharField(max_length=24, choices=Outcome.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlySubjectRiskQuerySet.as_manager()

    class Meta:
        db_table = "subject_risk_assessments"
        ordering = ("subject_version_id", "id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(outcome__in=("clear", "restricted", "review_required")),
                name="subject_risk_assessment_valid_outcome",
            )
        ]


class SubjectRiskHit(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assessment = models.ForeignKey(
        SubjectRiskAssessment,
        on_delete=models.PROTECT,
        related_name="hits",
    )
    risk_type_key = models.CharField(max_length=64)
    rule_key = models.CharField(max_length=64)
    reason_type = models.CharField(max_length=32, choices=SubjectRiskRule.ReasonType.choices)
    field_key = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlySubjectRiskQuerySet.as_manager()

    class Meta:
        db_table = "subject_risk_hits"
        ordering = ("assessment_id", "rule_key", "field_key", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("assessment", "rule_key", "field_key"),
                name="subject_risk_hit_rule_field_unique",
            )
        ]


class SubjectReview(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        PENDING = "pending", "\u5f85\u5ba1\u6838"
        APPROVED = "approved", "\u5df2\u901a\u8fc7"
        REJECTED = "rejected", "\u5df2\u62d2\u7edd"
        SUPERSEDED = "superseded", "\u5df2\u88ab\u65b0\u7248\u672c\u66ff\u4ee3"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assessment = models.OneToOneField(
        SubjectRiskAssessment,
        on_delete=models.PROTECT,
        related_name="review",
    )
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="reviews")
    subject_version = models.OneToOneField(
        SubjectVersion,
        on_delete=models.PROTECT,
        related_name="review",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    public_reason = models.CharField(max_length=500, blank=True)
    internal_note = models.CharField(max_length=1000, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_subjects",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "subject_reviews"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("status", "created_at", "id"), name="subject_review_queue_idx"),
            models.Index(fields=("subject", "created_at", "id"), name="subject_review_subject_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=("pending", "approved", "rejected", "superseded")),
                name="subject_review_valid_status",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1), name="subject_review_version_gte_1"
            ),
        ]


class SubjectReviewEvent(models.Model):  # noqa: DJ008
    class EventType(models.TextChoices):
        REQUESTED = "requested", "\u5df2\u8fdb\u5165\u5ba1\u6838"
        APPROVED = "approved", "\u5ba1\u6838\u901a\u8fc7"
        REJECTED = "rejected", "\u5ba1\u6838\u62d2\u7edd"
        SUPERSEDED = "superseded", "\u5df2\u88ab\u65b0\u7248\u672c\u66ff\u4ee3"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    review = models.ForeignKey(SubjectReview, on_delete=models.PROTECT, related_name="events")
    event_type = models.CharField(max_length=16, choices=EventType.choices)
    from_status = models.CharField(max_length=16, blank=True)
    to_status = models.CharField(max_length=16, choices=SubjectReview.Status.choices)
    safe_summary = models.JSONField(default=dict)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="subject_review_events",
    )
    request_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlySubjectRiskQuerySet.as_manager()

    class Meta:
        db_table = "subject_review_events"


class SubjectEnrichmentJobQuerySet(models.QuerySet):
    def delete(self):
        raise TypeError("Subject enrichment jobs cannot be deleted.")


class SubjectEnrichmentImmutableQuerySet(SubjectEnrichmentJobQuerySet):
    def update(self, **kwargs):
        raise TypeError("Subject enrichment evidence is append-only.")


class SubjectEnrichmentJob(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        RETRY_WAIT = "retry_wait", "Retry wait"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="subject_enrichment_jobs",
    )
    subject = models.ForeignKey(
        Subject,
        on_delete=models.PROTECT,
        related_name="enrichment_jobs",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    version = models.PositiveBigIntegerField(default=1)
    subject_object_version_at_create = models.PositiveBigIntegerField()
    current_formal_subject_version_id_at_create = models.UUIDField(null=True, blank=True)
    schema_digest = models.CharField(max_length=64)
    schema_snapshot_format_version = models.PositiveSmallIntegerField(default=1)
    target_manifest = models.JSONField(default=list)
    input_subject_values = models.JSONField(default=dict)
    provider_key = models.CharField(max_length=32)
    model_key = models.CharField(max_length=64)
    adapter_version = models.CharField(max_length=32)
    prompt_version = models.CharField(max_length=32)
    input_digest = models.CharField(max_length=64)
    output_digest = models.CharField(max_length=64, blank=True)
    idempotency_key_version = models.PositiveSmallIntegerField(default=1)
    idempotency_key_digest = models.CharField(max_length=64, unique=True)
    request_digest = models.CharField(max_length=64)
    generation = models.UUIDField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    retry_count = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    stable_error_code = models.CharField(max_length=64, blank=True)
    provider_metrics = models.JSONField(default=dict)
    request_id = models.UUIDField(null=True, blank=True)
    correlation_id = models.UUIDField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SubjectEnrichmentJobQuerySet.as_manager()

    class Meta:
        db_table = "subject_enrichment_jobs"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("subject", "status", "created_at"), name="subj_enrich_status_idx"),
            models.Index(fields=("status", "next_attempt_at"), name="subj_enrich_retry_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("subject",),
                condition=models.Q(status__in=("queued", "running", "retry_wait")),
                name="subject_enrichment_one_open",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=("queued", "running", "retry_wait", "succeeded", "failed")
                ),
                name="subject_enrichment_valid_status",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1), name="subject_enrichment_version_gte_1"
            ),
            models.CheckConstraint(
                condition=models.Q(subject_object_version_at_create__gte=1),
                name="subject_enrichment_subject_ver_gte_1",
            ),
            models.CheckConstraint(
                condition=models.Q(attempts__gte=0) & models.Q(retry_count__gte=0),
                name="subject_enrichment_retry_counts",
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
                        status__in=("succeeded", "failed"),
                        generation__isnull=False,
                        finished_at__isnull=False,
                    )
                ),
                name="subject_enrichment_status_fields",
            ),
        ]

    def delete(self, *args, **kwargs):
        raise TypeError("Subject enrichment jobs cannot be deleted.")


class SubjectEnrichmentSource(models.Model):  # noqa: DJ008
    class SourceType(models.TextChoices):
        DOCUMENT = "document", "Document"
        WEB = "web", "Web"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(SubjectEnrichmentJob, on_delete=models.PROTECT, related_name="sources")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT)
    source_type = models.CharField(max_length=16, choices=SourceType.choices)
    document_parsed_version = models.ForeignKey(
        "documents.DocumentParsedVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="subject_enrichment_sources",
    )
    web_parsed_version = models.ForeignKey(
        "web_sources.WebSourceParsedVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="subject_enrichment_sources",
    )
    content_digest = models.CharField(max_length=64)
    input_characters = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    objects = SubjectEnrichmentImmutableQuerySet.as_manager()

    class Meta:
        db_table = "subject_enrichment_sources"
        ordering = ("job_id", "source_type", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("job", "document_parsed_version"),
                condition=models.Q(source_type="document"),
                name="subj_enrich_doc_source_unique",
            ),
            models.UniqueConstraint(
                fields=("job", "web_parsed_version"),
                condition=models.Q(source_type="web"),
                name="subj_enrich_web_source_unique",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        source_type="document",
                        document_parsed_version__isnull=False,
                        web_parsed_version__isnull=True,
                    )
                    | models.Q(
                        source_type="web",
                        document_parsed_version__isnull=True,
                        web_parsed_version__isnull=False,
                    )
                ),
                name="subject_enrichment_source_binding",
            ),
            models.CheckConstraint(
                condition=models.Q(input_characters__gte=1), name="subject_enrichment_source_chars"
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Subject enrichment sources are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Subject enrichment sources are immutable.")


class SubjectEnrichmentSuggestion(models.Model):  # noqa: DJ008
    class Confidence(models.TextChoices):
        HIGH = "high", "High"
        MEDIUM = "medium", "Medium"
        LOW = "low", "Low"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(
        SubjectEnrichmentJob, on_delete=models.PROTECT, related_name="suggestions"
    )
    field_key = models.CharField(max_length=64)
    suggested_value = models.JSONField(null=True, blank=True)
    value_digest = models.CharField(max_length=64)
    confidence = models.CharField(max_length=16, choices=Confidence.choices)
    conflict = models.BooleanField(default=False)
    conflict_code = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = SubjectEnrichmentImmutableQuerySet.as_manager()

    class Meta:
        db_table = "subject_enrichment_suggestions"
        ordering = ("job_id", "field_key", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("job", "field_key"), name="subject_enrichment_job_field_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(confidence__in=("high", "medium", "low")),
                name="subject_enrichment_confidence_valid",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Subject enrichment suggestions are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Subject enrichment suggestions are immutable.")


class SubjectEnrichmentSuggestionSource(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    suggestion = models.ForeignKey(
        SubjectEnrichmentSuggestion, on_delete=models.PROTECT, related_name="source_links"
    )
    source = models.ForeignKey(
        SubjectEnrichmentSource, on_delete=models.PROTECT, related_name="suggestion_links"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = SubjectEnrichmentImmutableQuerySet.as_manager()

    class Meta:
        db_table = "subject_enrichment_suggestion_sources"
        constraints = [
            models.UniqueConstraint(
                fields=("suggestion", "source"), name="subject_enrichment_citation_unique"
            )
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Subject enrichment citations are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Subject enrichment citations are immutable.")


class SubjectEnrichmentConfirmation(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.OneToOneField(
        SubjectEnrichmentJob, on_delete=models.PROTECT, related_name="confirmation"
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT)
    subject_version_before = models.PositiveBigIntegerField()
    subject_version_after = models.PositiveBigIntegerField()
    request_digest = models.CharField(max_length=64)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="confirmed_subject_enrichments",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = SubjectEnrichmentImmutableQuerySet.as_manager()

    class Meta:
        db_table = "subject_enrichment_confirmations"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(subject_version_before__gte=1),
                name="subject_enrichment_confirm_before_gte_1",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(subject_version_after=models.F("subject_version_before"))
                    | models.Q(subject_version_after=models.F("subject_version_before") + 1)
                ),
                name="subject_enrichment_confirm_version_step",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Subject enrichment confirmations are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Subject enrichment confirmations are immutable.")


class SubjectEnrichmentDecision(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    confirmation = models.ForeignKey(
        SubjectEnrichmentConfirmation, on_delete=models.PROTECT, related_name="decisions"
    )
    suggestion = models.OneToOneField(
        SubjectEnrichmentSuggestion, on_delete=models.PROTECT, related_name="decision"
    )
    accepted = models.BooleanField()
    created_at = models.DateTimeField(auto_now_add=True)

    objects = SubjectEnrichmentImmutableQuerySet.as_manager()

    class Meta:
        db_table = "subject_enrichment_decisions"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Subject enrichment decisions are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Subject enrichment decisions are immutable.")


class SubjectEnrichmentEvent(models.Model):  # noqa: DJ008
    class EventType(models.TextChoices):
        STARTED = "started", "Started"
        RETRY_SCHEDULED = "retry_scheduled", "Retry scheduled"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        APPLIED = "applied", "Applied"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(SubjectEnrichmentJob, on_delete=models.PROTECT, related_name="events")
    event_type = models.CharField(max_length=24, choices=EventType.choices)
    stable_error_code = models.CharField(max_length=64, blank=True)
    safe_summary = models.JSONField(default=dict)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="subject_enrichment_events",
    )
    request_id = models.UUIDField(null=True, blank=True)
    correlation_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = SubjectEnrichmentImmutableQuerySet.as_manager()

    class Meta:
        db_table = "subject_enrichment_events"
        ordering = ("job_id", "created_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    event_type__in=(
                        "started",
                        "retry_scheduled",
                        "succeeded",
                        "failed",
                        "applied",
                    )
                ),
                name="subject_enrichment_event_type_valid",
            )
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Subject enrichment events are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Subject enrichment events are immutable.")
