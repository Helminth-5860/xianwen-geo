from rest_framework import serializers

from apps.admin_rbac.serializers import StrictSerializer

from .catalog import MODEL_KEYS, MODEL_NAMES
from .models import Plan, PlanLimitDefinition, PlanVersion


class RiskFieldsSerializer(StrictSerializer):
    confirmed = serializers.BooleanField(required=False, default=False)
    current_password = serializers.CharField(
        required=False, default="", allow_blank=True, max_length=128, write_only=True
    )


class PlanCreatePayloadSerializer(StrictSerializer):
    code = serializers.CharField(max_length=64, trim_whitespace=False)
    name = serializers.CharField(max_length=100, trim_whitespace=False)
    description = serializers.CharField(
        required=False, default="", allow_blank=True, max_length=5000, trim_whitespace=False
    )
    price_display_mode = serializers.ChoiceField(choices=Plan.PriceDisplayMode.values)
    display_price = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, max_length=32
    )
    is_trial = serializers.BooleanField(required=False, default=False)
    sort_order = serializers.IntegerField(required=False, default=0, min_value=0)


class PlanCreateRequestSerializer(PlanCreatePayloadSerializer):
    confirmed = serializers.BooleanField(required=False, default=False)
    current_password = serializers.CharField(
        required=False, default="", allow_blank=True, max_length=128, write_only=True
    )


class PlanUpdatePayloadSerializer(StrictSerializer):
    code = serializers.CharField(required=False, max_length=64, trim_whitespace=False)
    name = serializers.CharField(required=False, max_length=100, trim_whitespace=False)
    description = serializers.CharField(
        required=False, allow_blank=True, max_length=5000, trim_whitespace=False
    )
    price_display_mode = serializers.ChoiceField(
        required=False, choices=Plan.PriceDisplayMode.values
    )
    display_price = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, max_length=32
    )
    is_trial = serializers.BooleanField(required=False)
    sort_order = serializers.IntegerField(required=False, min_value=0)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError({"non_field_errors": ["必须提供修改字段。"]})
        return attrs


class PlanUpdateRequestSerializer(PlanUpdatePayloadSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    confirmed = serializers.BooleanField(required=False, default=False)
    current_password = serializers.CharField(
        required=False, default="", allow_blank=True, max_length=128, write_only=True
    )


class PlanCopyPayloadSerializer(StrictSerializer):
    new_plan_id = serializers.UUIDField()
    new_code = serializers.CharField(max_length=64, trim_whitespace=False)
    new_name = serializers.CharField(max_length=100, trim_whitespace=False)
    source_version_id = serializers.UUIDField(required=False, allow_null=True)


class PlanCopyRequestSerializer(StrictSerializer):
    new_code = serializers.CharField(max_length=64, trim_whitespace=False)
    new_name = serializers.CharField(max_length=100, trim_whitespace=False)
    source_version_id = serializers.UUIDField(required=False, allow_null=True)
    expected_source_plan_version = serializers.IntegerField(min_value=1)
    confirmed = serializers.BooleanField(required=False, default=False)
    current_password = serializers.CharField(
        required=False, default="", allow_blank=True, max_length=128, write_only=True
    )


class PlanVersionCreatePayloadSerializer(StrictSerializer):
    source_version_id = serializers.UUIDField(required=False, allow_null=True)


class PlanVersionCreateRequestSerializer(PlanVersionCreatePayloadSerializer):
    expected_plan_version = serializers.IntegerField(min_value=1)
    confirmed = serializers.BooleanField(required=False, default=False)
    current_password = serializers.CharField(
        required=False, default="", allow_blank=True, max_length=128, write_only=True
    )


class LimitValueSerializer(StrictSerializer):
    key = serializers.CharField(max_length=100)
    value = serializers.JSONField(allow_null=True)


class ModelPermissionInputSerializer(StrictSerializer):
    model_key = serializers.ChoiceField(choices=MODEL_KEYS)
    sort_order = serializers.IntegerField(min_value=0)
    selected_by_default = serializers.BooleanField(required=False, default=False)


class PlanVersionUpdatePayloadSerializer(StrictSerializer):
    valid_days = serializers.IntegerField(min_value=1, max_value=3650)
    queue_priority = serializers.IntegerField(min_value=0, max_value=1000)
    limits = LimitValueSerializer(many=True, allow_empty=False)
    model_permissions = ModelPermissionInputSerializer(many=True, allow_empty=False)


class PlanVersionUpdateRequestSerializer(PlanVersionUpdatePayloadSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    confirmed = serializers.BooleanField(required=False, default=False)
    current_password = serializers.CharField(
        required=False, default="", allow_blank=True, max_length=128, write_only=True
    )


class PlanPublishPayloadSerializer(StrictSerializer):
    confirm_informal_composite = serializers.BooleanField(required=False, default=False)


class PlanPublishRequestSerializer(PlanPublishPayloadSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    confirmed = serializers.BooleanField(required=False, default=False)
    current_password = serializers.CharField(
        required=False, default="", allow_blank=True, max_length=128, write_only=True
    )


class PlanExpectedVersionRequestSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    confirmed = serializers.BooleanField(required=False, default=False)
    current_password = serializers.CharField(
        required=False, default="", allow_blank=True, max_length=128, write_only=True
    )


class EmptyPlanPayloadSerializer(StrictSerializer):
    pass


def limit_value(item):
    if item.value_type == "integer":
        return item.integer_value
    if item.value_type == "boolean":
        return item.boolean_value
    if item.value_type in {"text", "enum"}:
        return item.text_value
    if item.json_value == {"value": None} and item.limit_key in {
        "business_record_retention_days",
        "document_retention_days_after_expiry",
    }:
        return None
    return item.json_value


class PlanSummarySerializer(serializers.ModelSerializer):
    current_published_version_id = serializers.UUIDField(allow_null=True, read_only=True)
    display_price = serializers.SerializerMethodField()

    class Meta:
        model = Plan
        fields: tuple[str, ...] = (
            "id",
            "code",
            "name",
            "description",
            "price_display_mode",
            "display_price",
            "display_currency",
            "is_trial",
            "status",
            "sort_order",
            "current_published_version_id",
            "version",
            "created_at",
            "updated_at",
        )

    def get_display_price(self, obj):
        return str(obj.display_price) if obj.display_price is not None else None


class PlanVersionSerializer(serializers.ModelSerializer):
    limits = serializers.SerializerMethodField()
    model_permissions = serializers.SerializerMethodField()
    supports_formal_composite = serializers.SerializerMethodField()

    class Meta:
        model = PlanVersion
        fields = (
            "id",
            "plan_id",
            "version_no",
            "status",
            "valid_days",
            "queue_priority",
            "version",
            "snapshot_generated_at",
            "published_at",
            "published_by_id",
            "retired_at",
            "retired_by_id",
            "limits",
            "model_permissions",
            "supports_formal_composite",
            "created_at",
            "updated_at",
        )

    def get_limits(self, obj):
        return [
            {
                "key": item.limit_key,
                "value_type": item.value_type,
                "value": limit_value(item),
            }
            for item in obj.limits.select_related("limit_definition").order_by("limit_key")
        ]

    def get_model_permissions(self, obj):
        return [
            {
                "model_key": item.model_key,
                "name": MODEL_NAMES[item.model_key],
                "sort_order": item.sort_order,
                "selected_by_default": item.selected_by_default,
            }
            for item in obj.model_permissions.order_by("sort_order", "model_key")
        ]

    def get_supports_formal_composite(self, obj):
        values = {item.limit_key: limit_value(item) for item in obj.limits.all()}
        models = list(obj.model_permissions.all())
        return (
            len(models) >= 6
            and values.get("max_models_per_detection", 0) >= 6
            and (
                values.get("allow_user_model_selection") is not False
                or sum(item.selected_by_default for item in models) >= 6
            )
        )


class PlanDetailSerializer(PlanSummarySerializer):
    current_published_version = PlanVersionSerializer(read_only=True)
    draft_version = serializers.SerializerMethodField()

    class Meta(PlanSummarySerializer.Meta):
        fields = (*PlanSummarySerializer.Meta.fields, "current_published_version", "draft_version")

    def get_draft_version(self, obj):
        draft = obj.versions.filter(status=PlanVersion.Status.DRAFT).first()
        return PlanVersionSerializer(draft).data if draft else None


class PlanLimitDefinitionSerializer(serializers.ModelSerializer):
    default = serializers.JSONField(source="default_value")

    class Meta:
        model = PlanLimitDefinition
        fields = (
            "key",
            "name",
            "category",
            "value_type",
            "storage_kind",
            "scope",
            "quota_type",
            "minimum",
            "maximum",
            "unit",
            "required",
            "default",
            "enum_values",
            "description",
            "status",
            "catalog_version",
            "sort_order",
        )
