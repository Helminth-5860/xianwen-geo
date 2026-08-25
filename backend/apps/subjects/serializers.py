from rest_framework import serializers

from apps.admin_rbac.serializers import StrictSerializer

from .models import (
    Subject,
    SubjectBusinessProfile,
    SubjectContext,
    SubjectFieldDefinition,
    SubjectFieldOption,
    SubjectName,
    SubjectProduct,
    SubjectType,
    SubjectTypeFieldConfig,
    SubjectVersion,
)
from .risk_services import subject_risk_summary
from .schema_snapshots import (
    FrozenSemanticError,
    derive_product_candidates,
    public_form_schema,
    values_digest,
)

NAME_ROLE_FIELD_TYPES = {
    "official_name": {"text", "single", "select"},
    "alias": {"text", "single", "select", "multi"},
    "english_name": {"text", "single", "select", "multi"},
    "product": {"text", "single", "select", "multi"},
}


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
        role = attrs.get("name_role", SubjectTypeFieldConfig.NameRole.NONE)
        if role != SubjectTypeFieldConfig.NameRole.NONE and attrs["field_type"] not in (
            NAME_ROLE_FIELD_TYPES.get(role, set())
        ):
            raise serializers.ValidationError(
                {
                    "name_role": [
                        "\u5f53\u524d\u5b57\u6bb5\u7c7b\u578b\u4e0d\u652f\u6301\u8be5\u540d\u79f0\u8bed\u4e49\u89d2\u8272\u3002"
                    ]
                }
            )
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


class SubjectCreateRequestSerializer(StrictSerializer):
    subject_type_id = serializers.UUIDField()
    expected_schema_version = serializers.IntegerField(min_value=1)
    initial_values = serializers.DictField(required=False, default=dict)


class SubjectSocialChannelsSerializer(StrictSerializer):
    douyin = serializers.CharField(required=False, allow_blank=True, default="", max_length=1000)
    wechat_channels = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=1000
    )
    wechat_official_account = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=1000
    )
    xiaohongshu = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=1000
    )
    kuaishou = serializers.CharField(required=False, allow_blank=True, default="", max_length=1000)
    ecommerce_urls = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=5000
    )
    other_public_urls = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=5000
    )


class SubjectBusinessProfileInputSerializer(StrictSerializer):
    legal_entity_type = serializers.ChoiceField(
        choices=SubjectBusinessProfile.LegalEntityType.values
    )
    contact_name = serializers.CharField(max_length=100)
    contact_phone = serializers.RegexField(regex=r"^[0-9+()\-\s]{5,32}$", max_length=32)
    business_address = serializers.CharField(max_length=500)
    primary_business = serializers.CharField(max_length=5000)
    brand_name = serializers.CharField(required=False, allow_blank=True, default="", max_length=200)
    social_channels = SubjectSocialChannelsSerializer(required=False, default=dict)


class SubjectBusinessProfileSerializer(serializers.ModelSerializer):
    social_channels = SubjectSocialChannelsSerializer()

    class Meta:
        model = SubjectBusinessProfile
        fields = (
            "legal_entity_type",
            "contact_name",
            "contact_phone",
            "business_address",
            "primary_business",
            "brand_name",
            "social_channels",
        )


class SubjectDraftUpdateRequestSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    values = serializers.DictField()
    profile_values = SubjectBusinessProfileInputSerializer(required=False)


class SubjectSaveRequestSerializer(SubjectDraftUpdateRequestSerializer):
    pass


class SubjectStatusRequestSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)


class SubjectCurrentRequestSerializer(StrictSerializer):
    subject_id = serializers.UUIDField()
    expected_version = serializers.IntegerField(min_value=1)


class SubjectProductConfirmationSerializer(StrictSerializer):
    candidate_key = serializers.CharField(min_length=64, max_length=64)
    uniqueness_confirmed = serializers.BooleanField()
    include_in_mention = serializers.BooleanField()


class SubjectCommitRequestSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    products = SubjectProductConfirmationSerializer(many=True, allow_empty=True)


class SubjectNameSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubjectName
        fields = ("role", "display_value", "source_field_key")


class SubjectProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubjectProduct
        fields = (
            "candidate_key",
            "display_value",
            "source_field_key",
            "uniqueness_confirmed",
            "include_in_mention",
        )


class SubjectVersionSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = SubjectVersion
        fields = ("id", "version_no", "official_name", "created_at")


class SubjectVersionDetailSerializer(SubjectVersionSummarySerializer):
    form_schema = serializers.SerializerMethodField()
    names = SubjectNameSerializer(many=True, read_only=True)
    products = SubjectProductSerializer(many=True, read_only=True)

    class Meta:
        model = SubjectVersion
        fields = (
            "id",
            "version_no",
            "official_name",
            "created_at",
            "schema_version",
            "field_values",
            "form_schema",
            "names",
            "products",
        )

    def get_form_schema(self, obj):
        return public_form_schema(obj.schema_snapshot)


class SubjectSummarySerializer(serializers.ModelSerializer):
    subject_type = serializers.SerializerMethodField()
    is_current = serializers.SerializerMethodField()
    current_version_no = serializers.SerializerMethodField()
    official_name = serializers.SerializerMethodField()
    service_regions = serializers.SerializerMethodField()

    class Meta:
        model = Subject
        fields = (
            "id",
            "subject_type",
            "status",
            "version",
            "is_current",
            "current_version_no",
            "official_name",
            "service_regions",
            "retest_required",
            "created_at",
            "updated_at",
        )

    def get_subject_type(self, obj):
        snapshot_type = obj.schema_snapshot["subject_type"]
        return {
            "id": snapshot_type["id"],
            "key": snapshot_type["key"],
            "name": snapshot_type["name"],
            "icon_key": snapshot_type["icon_key"],
        }

    def get_is_current(self, obj):
        return obj.pk == self.context.get("current_subject_id")

    def get_current_version_no(self, obj):
        return obj.current_version.version_no if obj.current_version_id else None

    def get_official_name(self, obj):
        if obj.current_version_id:
            return obj.current_version.official_name
        draft_name = obj.draft_values.get("name")
        return draft_name.strip() if isinstance(draft_name, str) and draft_name.strip() else None

    def get_service_regions(self, obj):
        values = obj.current_version.field_values if obj.current_version_id else obj.draft_values
        service_regions = values.get("service_regions")
        return service_regions if isinstance(service_regions, str) else ""


class SubjectDetailSerializer(SubjectSummarySerializer):
    business_profile = serializers.SerializerMethodField()
    form_schema = serializers.SerializerMethodField()
    product_candidates = serializers.SerializerMethodField()
    has_uncommitted_changes = serializers.SerializerMethodField()
    risk = serializers.SerializerMethodField()

    class Meta:
        model = Subject
        fields = (
            "id",
            "subject_type",
            "status",
            "version",
            "is_current",
            "current_version_no",
            "official_name",
            "retest_required",
            "created_at",
            "updated_at",
            "schema_version",
            "draft_values",
            "business_profile",
            "form_schema",
            "product_candidates",
            "has_uncommitted_changes",
            "risk",
        )

    def get_form_schema(self, obj):
        return public_form_schema(obj.schema_snapshot)

    def get_business_profile(self, obj):
        try:
            profile = obj.business_profile
        except SubjectBusinessProfile.DoesNotExist:
            return {
                "legal_entity_type": "",
                "contact_name": "",
                "contact_phone": "",
                "business_address": "",
                "primary_business": "",
                "brand_name": "",
                "social_channels": SubjectSocialChannelsSerializer({}).data,
            }
        return SubjectBusinessProfileSerializer(profile).data

    def get_product_candidates(self, obj):
        try:
            candidates = derive_product_candidates(obj.schema_snapshot, obj.draft_values)
        except FrozenSemanticError:
            return []
        return [
            {
                "candidate_key": item["candidate_key"],
                "display_value": item["display_value"],
                "source_field_key": item["source_field_key"],
            }
            for item in candidates
        ]

    def get_has_uncommitted_changes(self, obj):
        if obj.current_version_id is None:
            return True
        return values_digest(obj.draft_values) != obj.current_version.field_values_digest

    def get_risk(self, obj):
        return subject_risk_summary(obj)


class SubjectContextSerializer(serializers.ModelSerializer):
    current_subject_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = SubjectContext
        fields = ("current_subject_id", "version")
