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


class PlanApplication(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        PENDING = "pending", "待处理"
        CONTACTED = "contacted", "已联系"
        CLOSED = "closed", "已关闭"
        CANCELLED = "cancelled", "已取消"
        ACTIVATED = "activated", "已开通"

    class Source(models.TextChoices):
        USER_WEB = "user_web", "用户网页"

    OPEN_STATUSES = (Status.PENDING, Status.CONTACTED)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    applicant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="plan_applications"
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="applications")
    requested_plan_version = models.ForeignKey(
        PlanVersion, on_delete=models.PROTECT, related_name="applications"
    )
    requested_version_no = models.PositiveBigIntegerField()
    requested_config_digest = models.CharField(max_length=64)
    public_plan_snapshot = models.JSONField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.USER_WEB)
    user_note = models.CharField(max_length=500, blank=True)
    contacted_at = models.DateTimeField(null=True, blank=True)
    contacted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="contacted_plan_applications",
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="closed_plan_applications",
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    activated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="activated_plan_applications",
    )
    version = models.PositiveBigIntegerField(default=1)
    idempotency_key_digest = models.CharField(max_length=64)
    request_digest = models.CharField(max_length=64)
    request_id = models.UUIDField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "plan_applications"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(
                fields=("applicant", "status", "created_at"), name="plan_app_user_status_idx"
            ),
            models.Index(fields=("plan", "status", "created_at"), name="plan_app_plan_status_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("applicant", "idempotency_key_digest"), name="plan_app_idempotency_unique"
            ),
            models.UniqueConstraint(
                fields=("applicant", "plan"),
                condition=models.Q(status__in=("pending", "contacted")),
                name="plan_app_single_open",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=("pending", "contacted", "closed", "cancelled", "activated")
                ),
                name="plan_app_valid_status",
            ),
            models.CheckConstraint(
                condition=models.Q(source="user_web"), name="plan_app_valid_source"
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1), name="plan_app_version_gte_1"
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(requested_config_digest="")
                    & ~models.Q(idempotency_key_digest="")
                    & ~models.Q(request_digest="")
                ),
                name="plan_app_digests_present",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status="pending",
                        contacted_at__isnull=True,
                        closed_at__isnull=True,
                        cancelled_at__isnull=True,
                        activated_at__isnull=True,
                    )
                    | models.Q(
                        status="contacted",
                        contacted_at__isnull=False,
                        closed_at__isnull=True,
                        cancelled_at__isnull=True,
                        activated_at__isnull=True,
                    )
                    | models.Q(
                        status="closed",
                        closed_at__isnull=False,
                        cancelled_at__isnull=True,
                        activated_at__isnull=True,
                    )
                    | models.Q(
                        status="cancelled",
                        cancelled_at__isnull=False,
                        closed_at__isnull=True,
                        activated_at__isnull=True,
                    )
                    | models.Q(
                        status="activated",
                        activated_at__isnull=False,
                        closed_at__isnull=True,
                        cancelled_at__isnull=True,
                    )
                ),
                name="plan_app_status_times",
            ),
        ]


class AppendOnlyPlanApplicationEventQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError("套餐申请事件不允许更新。")

    def delete(self):
        raise TypeError("套餐申请事件不允许删除。")


class PlanApplicationEvent(models.Model):  # noqa: DJ008
    class EventType(models.TextChoices):
        SUBMITTED = "submitted", "已提交"
        CONTACTED = "contacted", "已联系"
        CLOSED = "closed", "已关闭"
        CANCELLED = "cancelled", "已取消"

        ACTIVATED = "activated", "已开通"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey(
        PlanApplication, on_delete=models.PROTECT, related_name="events"
    )
    event_type = models.CharField(max_length=16, choices=EventType.choices)
    from_status = models.CharField(max_length=16, blank=True)
    to_status = models.CharField(max_length=16, choices=PlanApplication.Status.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="plan_application_events",
    )
    safe_summary = models.CharField(max_length=200)
    request_id = models.UUIDField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlyPlanApplicationEventQuerySet.as_manager()

    class Meta:
        db_table = "plan_application_events"
        ordering = ("created_at", "id")
        indexes = [
            models.Index(fields=("application", "created_at"), name="plan_app_event_created_idx")
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    event_type__in=("submitted", "contacted", "closed", "cancelled", "activated")
                ),
                name="plan_app_event_valid_type",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    to_status__in=("pending", "contacted", "closed", "cancelled", "activated")
                ),
                name="plan_app_event_valid_status",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk and not self._state.adding:
            raise TypeError("套餐申请事件不允许更新。")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("套餐申请事件不允许删除。")


class SubscriptionQuerySet(models.QuerySet):
    def delete(self):
        raise TypeError("订阅不允许删除。")


class Subscription(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        ACTIVE = "active", "生效中"
        EXPIRED = "expired", "已到期"
        TERMINATED = "terminated", "已终止"

    class SourceType(models.TextChoices):
        APPLICATION = "application", "套餐申请"
        TRIAL_GRANT = "trial_grant", "试用发放"
        PLAN_CHANGE = "plan_change", "套餐变更"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="subscriptions",
    )
    source_application = models.OneToOneField(
        PlanApplication,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="subscription",
    )
    source_type = models.CharField(
        max_length=16,
        choices=SourceType.choices,
        default=SourceType.APPLICATION,
    )
    source_change = models.OneToOneField(
        "SubscriptionChange",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="target_subscription",
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    plan_version = models.ForeignKey(
        PlanVersion,
        on_delete=models.PROTECT,
        related_name="subscriptions",
    )
    plan_version_no = models.PositiveBigIntegerField()
    entitlement_snapshot = models.JSONField()
    entitlement_digest = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    cycle_anchor_day = models.PositiveSmallIntegerField()
    cycle_anchor_time = models.TimeField()
    is_trial = models.BooleanField()
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="opened_subscriptions",
    )
    opening_note = models.CharField(max_length=500, blank=True)
    activated_at = models.DateTimeField()
    expired_at = models.DateTimeField(null=True, blank=True)
    terminated_at = models.DateTimeField(null=True, blank=True)
    terminated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="terminated_subscriptions",
    )
    termination_reason = models.CharField(max_length=500, blank=True)
    version = models.PositiveBigIntegerField(default=1)
    request_id = models.UUIDField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SubscriptionQuerySet.as_manager()

    class Meta:
        db_table = "subscriptions"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("user", "status", "created_at"), name="subscription_user_idx"),
            models.Index(fields=("status", "ends_at"), name="subscription_expiry_idx"),
            models.Index(fields=("plan", "status", "created_at"), name="subscription_plan_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("user",),
                condition=models.Q(status="active"),
                name="subscription_single_active",
            ),
            models.UniqueConstraint(
                fields=("user",),
                condition=models.Q(is_trial=True),
                name="subscription_single_trial_history",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("active", "expired", "terminated")),
                name="subscription_valid_status",
            ),
            models.CheckConstraint(
                condition=models.Q(starts_at__lt=models.F("ends_at")),
                name="subscription_valid_window",
            ),
            models.CheckConstraint(
                condition=models.Q(cycle_anchor_day__gte=1) & models.Q(cycle_anchor_day__lte=31),
                name="subscription_anchor_range",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="subscription_version_gte_1",
            ),
            models.CheckConstraint(
                condition=~models.Q(entitlement_digest=""),
                name="subscription_digest_present",
            ),
            models.CheckConstraint(
                condition=models.Q(source_type__in=("application", "trial_grant", "plan_change")),
                name="subscription_source_type_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        source_type="application",
                        is_trial=False,
                        source_application__isnull=False,
                        source_change__isnull=True,
                    )
                    | models.Q(
                        source_type="trial_grant",
                        is_trial=True,
                        source_application__isnull=True,
                        source_change__isnull=True,
                    )
                    | models.Q(
                        source_type="plan_change",
                        is_trial=False,
                        source_application__isnull=True,
                        source_change__isnull=False,
                    )
                ),
                name="subscription_source_consistent",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status="active",
                        expired_at__isnull=True,
                        terminated_at__isnull=True,
                        termination_reason="",
                    )
                    | models.Q(
                        status="expired",
                        expired_at__isnull=False,
                        terminated_at__isnull=True,
                        termination_reason="",
                    )
                    | models.Q(
                        status="terminated",
                        expired_at__isnull=True,
                        terminated_at__isnull=False,
                        terminated_by__isnull=False,
                        termination_reason__gt="",
                    )
                ),
                name="subscription_status_times",
            ),
        ]

    def delete(self, *args, **kwargs):
        raise TypeError("订阅不允许删除。")


class AppendOnlySubscriptionEventQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError("订阅事件不允许更新。")

    def delete(self):
        raise TypeError("订阅事件不允许删除。")


class SubscriptionEvent(models.Model):  # noqa: DJ008
    class EventType(models.TextChoices):
        ACTIVATED = "activated", "已生效"
        EXPIRED = "expired", "已到期"
        TERMINATED = "terminated", "已终止"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.PROTECT,
        related_name="events",
    )
    event_type = models.CharField(max_length=16, choices=EventType.choices)
    from_status = models.CharField(max_length=16, blank=True)
    to_status = models.CharField(max_length=16, choices=Subscription.Status.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="subscription_events",
    )
    safe_summary = models.CharField(max_length=200)
    request_id = models.UUIDField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlySubscriptionEventQuerySet.as_manager()

    class Meta:
        db_table = "subscription_events"
        ordering = ("created_at", "id")
        indexes = [
            models.Index(fields=("subscription", "created_at"), name="subscription_event_idx")
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(event_type__in=("activated", "expired", "terminated")),
                name="subscription_event_valid_type",
            ),
            models.CheckConstraint(
                condition=models.Q(to_status__in=("active", "expired", "terminated")),
                name="subscription_event_valid_status",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk and not self._state.adding:
            raise TypeError("订阅事件不允许更新。")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("订阅事件不允许删除。")


class SubscriptionChangeQuerySet(models.QuerySet):
    def delete(self):
        raise TypeError("订阅变更不允许删除。")


class SubscriptionChange(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "已排期"
        EXECUTED = "executed", "已执行"
        CANCELLED = "cancelled", "已取消"
        FAILED = "failed", "Failed"

    class ChangeType(models.TextChoices):
        RENEWAL = "renewal", "续费"
        UPGRADE = "upgrade", "升级"
        DOWNGRADE = "downgrade", "降级"
        REPLACEMENT = "replacement", "替换"
        TRIAL_CONVERSION = "trial_conversion", "试用转正式"

    class QuotaPolicy(models.TextChoices):
        OVERWRITE = "overwrite", "覆盖"
        ACCUMULATE = "accumulate", "累加"
        RETAIN = "retain", "保留"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="subscription_changes",
    )
    from_subscription = models.ForeignKey(
        Subscription,
        on_delete=models.PROTECT,
        related_name="outgoing_changes",
    )
    target_plan = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        related_name="subscription_changes",
    )
    target_plan_version = models.ForeignKey(
        PlanVersion,
        on_delete=models.PROTECT,
        related_name="subscription_changes",
    )
    target_plan_version_no = models.PositiveBigIntegerField()
    target_entitlement_digest = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices)
    change_type = models.CharField(max_length=24, choices=ChangeType.choices)
    quota_policy = models.CharField(max_length=16, choices=QuotaPolicy.choices)
    effective_at = models.DateTimeField()
    reason = models.CharField(max_length=500)
    unavailable_reason = models.CharField(max_length=500, blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="requested_subscription_changes",
    )
    source_approval = models.OneToOneField(
        "admin_rbac.ApprovalRequest",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="scheduled_subscription_change",
    )
    executed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    stable_error_code = models.CharField(max_length=64, blank=True)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    retry_count = models.PositiveIntegerField(default=0)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="cancelled_subscription_changes",
    )
    cancellation_reason = models.CharField(max_length=500, blank=True)
    version = models.PositiveBigIntegerField(default=1)
    idempotency_key_version = models.PositiveSmallIntegerField(default=1)
    idempotency_key_digest = models.CharField(max_length=64, unique=True)
    idempotency_scope_digest = models.CharField(max_length=64)
    request_digest = models.CharField(max_length=64)
    cancellation_idempotency_key_version = models.PositiveSmallIntegerField(null=True)
    cancellation_idempotency_key_digest = models.CharField(  # noqa: DJ001
        max_length=64, null=True, unique=True
    )
    cancellation_idempotency_scope_digest = models.CharField(max_length=64, blank=True)
    cancellation_request_digest = models.CharField(max_length=64, blank=True)
    request_id = models.UUIDField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SubscriptionChangeQuerySet.as_manager()

    class Meta:
        db_table = "subscription_changes"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("user", "created_at"), name="sub_change_user_idx"),
            models.Index(fields=("status", "effective_at"), name="sub_change_due_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("from_subscription",),
                condition=models.Q(status__in=("scheduled", "executed")),
                name="sub_change_single_successor",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("scheduled", "executed", "cancelled", "failed")),
                name="sub_change_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    change_type__in=(
                        "renewal",
                        "upgrade",
                        "downgrade",
                        "replacement",
                        "trial_conversion",
                    )
                ),
                name="sub_change_type_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(quota_policy__in=("overwrite", "accumulate", "retain")),
                name="sub_change_quota_policy_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status="scheduled",
                        change_type="renewal",
                        executed_at__isnull=True,
                        cancelled_at__isnull=True,
                        cancelled_by__isnull=True,
                        cancellation_reason="",
                        failed_at__isnull=True,
                    )
                    | models.Q(
                        status="executed",
                        executed_at__isnull=False,
                        cancelled_at__isnull=True,
                        cancelled_by__isnull=True,
                        cancellation_reason="",
                        failed_at__isnull=True,
                        stable_error_code="",
                    )
                    | models.Q(
                        status="cancelled",
                        change_type="renewal",
                        executed_at__isnull=True,
                        cancelled_at__isnull=False,
                        cancelled_by__isnull=False,
                        cancellation_reason__gt="",
                        failed_at__isnull=True,
                        stable_error_code="",
                    )
                    | models.Q(
                        status="failed",
                        change_type="renewal",
                        executed_at__isnull=True,
                        cancelled_at__isnull=True,
                        cancelled_by__isnull=True,
                        cancellation_reason="",
                        failed_at__isnull=False,
                        stable_error_code__gt="",
                    )
                ),
                name="sub_change_status_times",
            ),
            models.CheckConstraint(
                condition=(
                    (
                        models.Q(status__in=("scheduled", "executed", "failed"))
                        & models.Q(cancellation_idempotency_key_version__isnull=True)
                        & models.Q(cancellation_idempotency_key_digest__isnull=True)
                        & models.Q(cancellation_idempotency_scope_digest="")
                        & models.Q(cancellation_request_digest="")
                    )
                    | (
                        models.Q(status="cancelled")
                        & models.Q(cancellation_idempotency_key_version__isnull=False)
                        & models.Q(cancellation_idempotency_key_digest__isnull=False)
                        & ~models.Q(cancellation_idempotency_scope_digest="")
                        & ~models.Q(cancellation_request_digest="")
                    )
                ),
                name="sub_change_cancel_idem_state",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(target_entitlement_digest="")
                    & ~models.Q(idempotency_key_digest="")
                    & ~models.Q(idempotency_scope_digest="")
                    & ~models.Q(request_digest="")
                    & models.Q(version__gte=1)
                ),
                name="sub_change_digests_version",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(status="scheduled", next_attempt_at__isnull=False)
                    | ~models.Q(status="scheduled")
                ),
                name="sub_change_retry_schedule",
            ),
        ]

    def delete(self, *args, **kwargs):
        raise TypeError("订阅变更不允许删除。")


class AppendOnlySubscriptionChangeEventQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError("订阅变更事件不允许更新。")

    def delete(self):
        raise TypeError("订阅变更事件不允许删除。")


class SubscriptionChangeEvent(models.Model):  # noqa: DJ008
    class EventType(models.TextChoices):
        SCHEDULED = "scheduled", "已排期"
        EXECUTED = "executed", "已执行"
        CANCELLED = "cancelled", "已取消"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    change = models.ForeignKey(
        SubscriptionChange,
        on_delete=models.PROTECT,
        related_name="events",
    )
    event_type = models.CharField(max_length=16, choices=EventType.choices)
    from_status = models.CharField(max_length=16, blank=True)
    to_status = models.CharField(max_length=16, choices=SubscriptionChange.Status.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="subscription_change_events",
    )
    safe_summary = models.CharField(max_length=200)
    request_id = models.UUIDField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlySubscriptionChangeEventQuerySet.as_manager()

    class Meta:
        db_table = "subscription_change_events"
        ordering = ("created_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(event_type__in=("scheduled", "executed", "cancelled", "failed")),
                name="sub_change_event_type_valid",
            )
        ]

    def save(self, *args, **kwargs):
        if self.pk and not self._state.adding:
            raise TypeError("订阅变更事件不允许更新。")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("订阅变更事件不允许删除。")
