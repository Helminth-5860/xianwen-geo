from rest_framework import serializers

from apps.admin_rbac.serializers import StrictSerializer

from .models import (
    SubjectReview,
    SubjectRiskCatalogRevision,
    SubjectRiskRule,
    SubjectRiskType,
    SubjectType,
)
from .risk_engine import RiskCatalogInvalid, normalize_patterns


class RiskTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubjectRiskType
        fields = (
            "id",
            "key",
            "name",
            "description",
            "enabled",
            "manual_review_required",
            "allow_geo_detection",
            "allow_article_generation",
            "allow_image_generation",
            "require_authoritative_citations",
            "require_disclaimer",
            "sort_order",
            "version",
            "created_at",
            "updated_at",
        )


class RiskTypeCreateSerializer(StrictSerializer):
    expected_catalog_version = serializers.IntegerField(min_value=1)
    key = serializers.RegexField(r"^[a-z][a-z0-9_.-]{0,63}$")
    name = serializers.CharField(min_length=1, max_length=100, trim_whitespace=True)
    description = serializers.CharField(max_length=500, allow_blank=True, default="")
    enabled = serializers.BooleanField(default=False)
    manual_review_required = serializers.BooleanField(default=True)
    allow_geo_detection = serializers.BooleanField(default=False)
    allow_article_generation = serializers.BooleanField(default=False)
    allow_image_generation = serializers.BooleanField(default=False)
    require_authoritative_citations = serializers.BooleanField(default=True)
    require_disclaimer = serializers.BooleanField(default=True)
    sort_order = serializers.IntegerField(min_value=0, default=0)


class RiskTypeUpdateSerializer(StrictSerializer):
    expected_catalog_version = serializers.IntegerField(min_value=1)
    expected_version = serializers.IntegerField(min_value=1)
    name = serializers.CharField(min_length=1, max_length=100, trim_whitespace=True, required=False)
    description = serializers.CharField(max_length=500, allow_blank=True, required=False)
    enabled = serializers.BooleanField(required=False)
    manual_review_required = serializers.BooleanField(required=False)
    allow_geo_detection = serializers.BooleanField(required=False)
    allow_article_generation = serializers.BooleanField(required=False)
    allow_image_generation = serializers.BooleanField(required=False)
    require_authoritative_citations = serializers.BooleanField(required=False)
    require_disclaimer = serializers.BooleanField(required=False)
    sort_order = serializers.IntegerField(min_value=0, required=False)


class RiskRuleSerializer(serializers.ModelSerializer):
    risk_type_key = serializers.CharField(source="risk_type.key", read_only=True)
    subject_type_key = serializers.CharField(
        source="subject_type.key", read_only=True, allow_null=True
    )

    class Meta:
        model = SubjectRiskRule
        fields = (
            "id",
            "key",
            "risk_type",
            "risk_type_key",
            "subject_type",
            "subject_type_key",
            "field_key",
            "operator",
            "patterns",
            "reason_type",
            "enabled",
            "priority",
            "version",
            "created_at",
            "updated_at",
        )


class RiskRuleCreateSerializer(StrictSerializer):
    expected_catalog_version = serializers.IntegerField(min_value=1)
    key = serializers.RegexField(r"^[a-z][a-z0-9_.-]{0,63}$")
    risk_type = serializers.PrimaryKeyRelatedField(queryset=SubjectRiskType.objects.all())
    subject_type = serializers.PrimaryKeyRelatedField(
        queryset=SubjectType.objects.all(),
        allow_null=True,
        required=False,
        default=None,
    )
    field_key = serializers.RegexField(
        r"^[a-z][a-z0-9_]{0,63}$", allow_blank=True, required=False, default=""
    )
    operator = serializers.ChoiceField(choices=SubjectRiskRule.Operator.choices)
    patterns = serializers.ListField(
        child=serializers.CharField(min_length=1, max_length=200),
        min_length=1,
        max_length=50,
    )
    reason_type = serializers.ChoiceField(choices=SubjectRiskRule.ReasonType.choices)
    enabled = serializers.BooleanField(default=False)
    priority = serializers.IntegerField(min_value=0, default=0)

    def validate_patterns(self, value):
        try:
            return normalize_patterns(value)
        except RiskCatalogInvalid as exc:
            raise serializers.ValidationError(
                "\u98ce\u9669\u89c4\u5219\u503c\u4e0d\u6b63\u786e\u3002"
            ) from exc


class RiskRuleUpdateSerializer(StrictSerializer):
    expected_catalog_version = serializers.IntegerField(min_value=1)
    expected_version = serializers.IntegerField(min_value=1)
    risk_type = serializers.PrimaryKeyRelatedField(
        queryset=SubjectRiskType.objects.all(), required=False
    )
    subject_type = serializers.PrimaryKeyRelatedField(
        queryset=SubjectType.objects.all(),
        allow_null=True,
        required=False,
    )
    field_key = serializers.RegexField(r"^[a-z][a-z0-9_]{0,63}$", allow_blank=True, required=False)
    operator = serializers.ChoiceField(choices=SubjectRiskRule.Operator.choices, required=False)
    patterns = serializers.ListField(
        child=serializers.CharField(min_length=1, max_length=200),
        min_length=1,
        max_length=50,
        required=False,
    )
    reason_type = serializers.ChoiceField(
        choices=SubjectRiskRule.ReasonType.choices, required=False
    )
    enabled = serializers.BooleanField(required=False)
    priority = serializers.IntegerField(min_value=0, required=False)

    def validate_patterns(self, value):
        try:
            return normalize_patterns(value)
        except RiskCatalogInvalid as exc:
            raise serializers.ValidationError(
                "\u98ce\u9669\u89c4\u5219\u503c\u4e0d\u6b63\u786e\u3002"
            ) from exc


class CatalogPublishSerializer(StrictSerializer):
    expected_catalog_version = serializers.IntegerField(min_value=1)
    confirmed = serializers.BooleanField(required=False, default=False)
    current_password = serializers.CharField(
        max_length=128, write_only=True, required=False, default="", trim_whitespace=False
    )


class CatalogRevisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubjectRiskCatalogRevision
        fields = ("id", "revision_no", "format_version", "snapshot_digest", "created_at")


class ReviewSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(source="subject.user_id", read_only=True)
    subject_id = serializers.UUIDField(read_only=True)
    subject_version_id = serializers.UUIDField(read_only=True)
    version_no = serializers.IntegerField(source="subject_version.version_no", read_only=True)
    official_name = serializers.CharField(source="subject_version.official_name", read_only=True)
    reason_types = serializers.SerializerMethodField()

    class Meta:
        model = SubjectReview
        fields = (
            "id",
            "user_id",
            "subject_id",
            "subject_version_id",
            "version_no",
            "official_name",
            "status",
            "reason_types",
            "reason",
            "version",
            "reviewed_at",
            "created_at",
            "updated_at",
        )

    def get_reason_types(self, obj):
        return sorted(set(obj.assessment.hits.values_list("reason_type", flat=True)))


class ReviewDecisionSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=500, allow_blank=True, required=False, default="")
