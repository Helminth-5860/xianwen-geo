import uuid

from django.conf import settings
from django.db import models
from django.db.models.functions import Lower

from .catalog import MODEL_KEYS


class Plan(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        PUBLISHED = "published", "已上架"
        OFFLINE = "offline", "已下架"
        ARCHIVED = "archived", "已归档"

    class PriceDisplayMode(models.TextChoices):
        FIXED = "fixed", "固定展示价格"
        CONTACT = "contact", "联系开通"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    price_display_mode = models.CharField(
        max_length=16,
        choices=PriceDisplayMode.choices,
        default=PriceDisplayMode.CONTACT,
    )
    display_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    display_currency = models.CharField(max_length=3, default="CNY", editable=False)
    is_trial = models.BooleanField(default=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    sort_order = models.PositiveIntegerField(default=0)
    current_published_version = models.ForeignKey(
        "PlanVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    version = models.PositiveBigIntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_plans",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_plans",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "plans"
        ordering = ("sort_order", "code", "id")
        indexes = [
            models.Index(fields=("status", "sort_order", "id"), name="plan_public_list_idx"),
        ]
        constraints = [
            models.UniqueConstraint(Lower("code"), name="plan_code_ci_unique"),
            models.CheckConstraint(
                condition=models.Q(status__in=("draft", "published", "offline", "archived")),
                name="plan_valid_status",
            ),
            models.CheckConstraint(
                condition=models.Q(price_display_mode__in=("fixed", "contact")),
                name="plan_valid_price_mode",
            ),
            models.CheckConstraint(
                condition=models.Q(display_currency="CNY"),
                name="plan_currency_cny",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        price_display_mode="fixed",
                        display_price__isnull=False,
                        display_price__gte=0,
                    )
                    | models.Q(price_display_mode="contact", display_price__isnull=True)
                ),
                name="plan_price_mode_value",
            ),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="plan_version_gte_1"),
        ]


class PlanVersion(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        PUBLISHED = "published", "已发布"
        RETIRED = "retired", "已退役"

    MIN_QUEUE_PRIORITY = 0
    MAX_QUEUE_PRIORITY = 1000

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="versions")
    version_no = models.PositiveBigIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    valid_days = models.PositiveBigIntegerField()
    queue_priority = models.PositiveIntegerField()
    effective_config = models.JSONField(null=True, blank=True)
    config_digest = models.CharField(max_length=64, blank=True)
    version = models.PositiveBigIntegerField(default=1)
    snapshot_generated_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="published_plan_versions",
    )
    retired_at = models.DateTimeField(null=True, blank=True)
    retired_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="retired_plan_versions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "plan_versions"
        ordering = ("plan_id", "-version_no", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("plan", "version_no"), name="plan_version_number_unique"
            ),
            models.UniqueConstraint(
                fields=("plan",),
                condition=models.Q(status="draft"),
                name="plan_single_draft",
            ),
            models.UniqueConstraint(
                fields=("plan",),
                condition=models.Q(status="published"),
                name="plan_single_published",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("draft", "published", "retired")),
                name="plan_version_valid_status",
            ),
            models.CheckConstraint(
                condition=models.Q(version_no__gte=1), name="plan_version_no_gte_1"
            ),
            models.CheckConstraint(
                condition=models.Q(valid_days__gte=1), name="plan_valid_days_gte_1"
            ),
            models.CheckConstraint(
                condition=models.Q(queue_priority__gte=0) & models.Q(queue_priority__lte=1000),
                name="plan_queue_priority_range",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1), name="plan_draft_version_gte_1"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status="draft",
                        effective_config__isnull=True,
                        config_digest="",
                        snapshot_generated_at__isnull=True,
                    )
                    | models.Q(
                        models.Q(
                            status__in=("published", "retired"),
                            effective_config__isnull=False,
                            snapshot_generated_at__isnull=False,
                        ),
                        ~models.Q(config_digest=""),
                    )
                ),
                name="plan_version_snapshot_by_status",
            ),
        ]


class PlanLimitDefinition(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        ACTIVE = "active", "启用"
        INACTIVE = "inactive", "停用"

    class ValueType(models.TextChoices):
        INTEGER = "integer", "整数"
        BOOLEAN = "boolean", "布尔"
        TEXT = "text", "文本"
        ENUM = "enum", "枚举"
        JSON = "json", "JSON"

    class StorageKind(models.TextChoices):
        PLAN_LIMIT = "plan_limit", "限制值表"
        PLAN_VERSION_FIELD = "plan_version_field", "版本字段"
        MODEL_PERMISSIONS = "model_permissions", "模型权限表"

    key = models.CharField(max_length=100, primary_key=True)
    name = models.CharField(max_length=100)
    category = models.CharField(max_length=50)
    value_type = models.CharField(max_length=16, choices=ValueType.choices)
    storage_kind = models.CharField(max_length=32, choices=StorageKind.choices)
    scope = models.CharField(max_length=32)
    quota_type = models.CharField(max_length=100, blank=True)
    minimum = models.BigIntegerField(null=True, blank=True)
    maximum = models.BigIntegerField(null=True, blank=True)
    unit = models.CharField(max_length=32, blank=True)
    required = models.BooleanField(default=False)
    default_value = models.JSONField(null=True, blank=True)
    enum_values = models.JSONField(default=list)
    json_schema = models.JSONField(default=dict)
    description = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    catalog_version = models.PositiveIntegerField(default=1)
    sort_order = models.PositiveIntegerField(default=0)
    semantic_digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "plan_limit_definitions"
        ordering = ("sort_order", "key")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=("active", "inactive")),
                name="plan_limit_definition_status",
            ),
            models.CheckConstraint(
                condition=models.Q(catalog_version__gte=1),
                name="plan_limit_catalog_version_gte_1",
            ),
        ]


class PlanLimit(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan_version = models.ForeignKey(PlanVersion, on_delete=models.PROTECT, related_name="limits")
    limit_definition = models.ForeignKey(
        PlanLimitDefinition,
        on_delete=models.PROTECT,
        related_name="plan_limits",
    )
    limit_key = models.CharField(max_length=100)
    value_type = models.CharField(max_length=16)
    integer_value = models.BigIntegerField(null=True, blank=True)
    boolean_value = models.BooleanField(null=True, blank=True)
    text_value = models.TextField(null=True, blank=True)  # noqa: DJ001
    json_value = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "plan_limits"
        ordering = ("limit_key", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("plan_version", "limit_definition"),
                name="plan_limit_definition_unique",
            ),
            models.UniqueConstraint(
                fields=("plan_version", "limit_key"),
                name="plan_limit_key_unique",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        value_type="integer",
                        integer_value__isnull=False,
                        boolean_value__isnull=True,
                        text_value__isnull=True,
                        json_value__isnull=True,
                    )
                    | models.Q(
                        value_type="boolean",
                        integer_value__isnull=True,
                        boolean_value__isnull=False,
                        text_value__isnull=True,
                        json_value__isnull=True,
                    )
                    | models.Q(
                        value_type__in=("text", "enum"),
                        integer_value__isnull=True,
                        boolean_value__isnull=True,
                        text_value__isnull=False,
                        json_value__isnull=True,
                    )
                    | models.Q(
                        value_type="json",
                        integer_value__isnull=True,
                        boolean_value__isnull=True,
                        text_value__isnull=True,
                        json_value__isnull=False,
                    )
                ),
                name="plan_limit_exact_typed_value",
            ),
        ]


class PlanModelPermission(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan_version = models.ForeignKey(
        PlanVersion, on_delete=models.PROTECT, related_name="model_permissions"
    )
    model_key = models.CharField(max_length=32)
    sort_order = models.PositiveIntegerField()
    selected_by_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "plan_model_permissions"
        ordering = ("sort_order", "model_key", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("plan_version", "model_key"),
                name="plan_model_key_unique",
            ),
            models.UniqueConstraint(
                fields=("plan_version", "sort_order"),
                name="plan_model_sort_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(model_key__in=MODEL_KEYS),
                name="plan_model_key_valid",
            ),
        ]
