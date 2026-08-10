from rest_framework import serializers

from apps.admin_rbac.serializers import StrictSerializer

from .models import (
    SubjectFieldDefinition,
    SubjectFieldOption,
    SubjectType,
    SubjectTypeFieldConfig,
)


class SubjectFieldOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubjectFieldOption
        fields = ("id", "option_key", "label", "enabled", "sort_order", "version")


class SubjectTypeFieldConfigSerializer(serializers.ModelSerializer):
    field_key = serializers.CharField(source="field_definition.field_key", read_only=True)
    field_type = serializers.CharField(source="field_definition.field_type", read_only=True)
    scope = serializers.CharField(source="field_definition.scope", read_only=True)
    is_builtin = serializers.BooleanField(source="field_definition.is_builtin", read_only=True)
    options = SubjectFieldOptionSerializer(many=True, read_only=True)

    class Meta:
        model = SubjectTypeFieldConfig
        fields = (
            "id",
            "field_key",
            "field_type",
            "scope",
            "is_builtin",
            "label",
            "description",
            "required",
            "default_value",
            "sort_order",
            "enabled",
            "used_for_ai",
            "name_role",
            "version",
            "options",
        )


class SubjectTypeSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = SubjectType
        fields = (
            "id",
            "key",
            "name",
            "description",
            "icon_key",
            "status",
            "sort_order",
            "is_builtin",
            "schema_version",
            "version",
        )


class SubjectTypeDetailSerializer(SubjectTypeSummarySerializer):
    fields = serializers.SerializerMethodField(method_name="get_schema_fields")  # type: ignore[assignment]

    class Meta(SubjectTypeSummarySerializer.Meta):
        fields = (*SubjectTypeSummarySerializer.Meta.fields, "fields", "created_at", "updated_at")  # type: ignore[assignment]

    def get_schema_fields(self, obj):
        configs = (
            obj.field_configs.select_related("field_definition")
            .prefetch_related("options")
            .order_by("sort_order", "id")
        )
        return SubjectTypeFieldConfigSerializer(configs, many=True).data


class PublicSubjectTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubjectType
        fields = ("id", "key", "name", "description", "icon_key", "sort_order", "schema_version")


class PublicFormSchemaSerializer(serializers.ModelSerializer):
    fields = serializers.SerializerMethodField(method_name="get_schema_fields")  # type: ignore[assignment]

    class Meta:
        model = SubjectType
        fields = ("id", "key", "name", "description", "icon_key", "schema_version", "fields")

    def get_schema_fields(self, obj):
        configs = (
            obj.field_configs.filter(enabled=True)
            .select_related("field_definition")
            .prefetch_related("options")
            .order_by("sort_order", "id")
        )
        data = SubjectTypeFieldConfigSerializer(configs, many=True).data
        for item in data:
            item.pop("is_builtin", None)
            item.pop("enabled", None)
            item.pop("version", None)
            item["options"] = [option for option in item["options"] if option["enabled"]]
            for option in item["options"]:
                option.pop("enabled", None)
                option.pop("version", None)
        return data


class SubjectTypeCreateSerializer(StrictSerializer):
    key = serializers.CharField(max_length=64, trim_whitespace=False)
    name = serializers.CharField(max_length=100, trim_whitespace=False)
    description = serializers.CharField(
        required=False, default="", allow_blank=True, max_length=500, trim_whitespace=False
    )
    icon_key = serializers.CharField(
        required=False, default="subject", max_length=64, trim_whitespace=False
    )
    sort_order = serializers.IntegerField(required=False, default=0, min_value=0)


class SubjectTypeUpdateSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    expected_schema_version = serializers.IntegerField(min_value=1)
    name = serializers.CharField(required=False, max_length=100, trim_whitespace=False)
    description = serializers.CharField(
        required=False, allow_blank=True, max_length=500, trim_whitespace=False
    )
    icon_key = serializers.CharField(required=False, max_length=64, trim_whitespace=False)
    sort_order = serializers.IntegerField(required=False, min_value=0)

    def validate(self, attrs):
        if set(attrs) == {"expected_version", "expected_schema_version"}:
            raise serializers.ValidationError({"non_field_errors": ["必须提供修改字段。"]})
        return attrs


class ExpectedSubjectTypeVersionsSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    expected_schema_version = serializers.IntegerField(min_value=1)


class OptionCreateInlineSerializer(StrictSerializer):
    option_key = serializers.CharField(max_length=64, trim_whitespace=False)
    label = serializers.CharField(max_length=100, trim_whitespace=False)  # type: ignore[assignment]
    enabled = serializers.BooleanField(required=False, default=True)
    sort_order = serializers.IntegerField(required=False, min_value=0)


class CustomFieldCreateSerializer(StrictSerializer):
    expected_schema_version = serializers.IntegerField(min_value=1)
    field_key = serializers.CharField(max_length=64, trim_whitespace=False)
    field_type = serializers.ChoiceField(choices=SubjectFieldDefinition.FieldType.values)
    label = serializers.CharField(max_length=100, trim_whitespace=False)  # type: ignore[assignment]
    description = serializers.CharField(
        required=False, default="", allow_blank=True, max_length=500, trim_whitespace=False
    )
    required = serializers.BooleanField(required=False, default=False)  # type: ignore[assignment]
    default_value = serializers.JSONField(required=False, allow_null=True, default=None)
    sort_order = serializers.IntegerField(required=False, default=0, min_value=0)
    enabled = serializers.BooleanField(required=False, default=False)
    used_for_ai = serializers.BooleanField(required=False, default=False)
    name_role = serializers.ChoiceField(
        required=False,
        default=SubjectTypeFieldConfig.NameRole.NONE,
        choices=SubjectTypeFieldConfig.NameRole.values,
    )
    options = OptionCreateInlineSerializer(many=True, required=False, default=list)

    def validate(self, attrs):
        choice = attrs["field_type"] in {
            SubjectFieldDefinition.FieldType.SINGLE,
            SubjectFieldDefinition.FieldType.MULTI,
            SubjectFieldDefinition.FieldType.SELECT,
        }
        if not choice and attrs.get("options"):
            raise serializers.ValidationError({"options": ["非选择字段不能配置选项。"]})
        if (
            attrs.get("enabled")
            and choice
            and not any(option.get("enabled", True) for option in attrs.get("options", []))
        ):
            raise serializers.ValidationError({"options": ["启用的选择字段至少需要一个启用选项。"]})
        if not attrs.get("enabled") and attrs.get("required"):
            raise serializers.ValidationError({"required": ["停用字段不能设为必填。"]})
        return attrs


class FieldConfigUpdateSerializer(StrictSerializer):
    expected_schema_version = serializers.IntegerField(min_value=1)
    expected_version = serializers.IntegerField(min_value=1)
    label = serializers.CharField(required=False, max_length=100, trim_whitespace=False)  # type: ignore[assignment]
    description = serializers.CharField(
        required=False, allow_blank=True, max_length=500, trim_whitespace=False
    )
    required = serializers.BooleanField(required=False)  # type: ignore[assignment]
    default_value = serializers.JSONField(required=False, allow_null=True)
    sort_order = serializers.IntegerField(required=False, min_value=0)
    enabled = serializers.BooleanField(required=False)
    used_for_ai = serializers.BooleanField(required=False)
    name_role = serializers.ChoiceField(
        required=False, choices=SubjectTypeFieldConfig.NameRole.values
    )

    def validate(self, attrs):
        if set(attrs) == {"expected_schema_version", "expected_version"}:
            raise serializers.ValidationError({"non_field_errors": ["必须提供修改字段。"]})
        return attrs


class FieldOptionCreateSerializer(StrictSerializer):
    expected_schema_version = serializers.IntegerField(min_value=1)
    expected_config_version = serializers.IntegerField(min_value=1)
    option_key = serializers.CharField(max_length=64, trim_whitespace=False)
    label = serializers.CharField(max_length=100, trim_whitespace=False)  # type: ignore[assignment]
    enabled = serializers.BooleanField(required=False, default=True)
    sort_order = serializers.IntegerField(required=False, default=0, min_value=0)


class FieldOptionUpdateSerializer(StrictSerializer):
    expected_schema_version = serializers.IntegerField(min_value=1)
    expected_version = serializers.IntegerField(min_value=1)
    label = serializers.CharField(required=False, max_length=100, trim_whitespace=False)  # type: ignore[assignment]
    enabled = serializers.BooleanField(required=False)
    sort_order = serializers.IntegerField(required=False, min_value=0)

    def validate(self, attrs):
        if set(attrs) == {"expected_schema_version", "expected_version"}:
            raise serializers.ValidationError({"non_field_errors": ["必须提供修改字段。"]})
        return attrs


class FieldOrderItemSerializer(StrictSerializer):
    id = serializers.UUIDField()
    expected_version = serializers.IntegerField(min_value=1)


class FieldOrderSerializer(StrictSerializer):
    expected_schema_version = serializers.IntegerField(min_value=1)
    fields = FieldOrderItemSerializer(many=True, allow_empty=False)  # type: ignore[assignment]
