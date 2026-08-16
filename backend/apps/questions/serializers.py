from rest_framework import serializers

from apps.admin_rbac.serializers import StrictSerializer

from .models import QuestionCategory, QuestionTag


class QuestionCategorySerializer(serializers.ModelSerializer):
    applicable_subject_type_ids = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = QuestionCategory
        fields = (
            "id",
            "key",
            "name",
            "description",
            "generation_guidance",
            "status",
            "sort_order",
            "is_builtin",
            "version",
            "applicable_subject_type_ids",
            "can_delete",
            "created_at",
            "updated_at",
        )

    def get_applicable_subject_type_ids(self, obj):
        return [
            str(pk)
            for pk in obj.applicable_subject_types.order_by("id").values_list("id", flat=True)
        ]

    def get_can_delete(self, obj):
        return False


class QuestionTagSerializer(serializers.ModelSerializer):
    applicable_subject_type_ids = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = QuestionTag
        fields = (
            "id",
            "key",
            "name",
            "description",
            "status",
            "sort_order",
            "is_builtin",
            "version",
            "applicable_subject_type_ids",
            "can_delete",
            "created_at",
            "updated_at",
        )

    def get_applicable_subject_type_ids(self, obj):
        return [
            str(pk)
            for pk in obj.applicable_subject_types.order_by("id").values_list("id", flat=True)
        ]

    def get_can_delete(self, obj):
        return False


class PublicQuestionCategorySerializer(QuestionCategorySerializer):
    class Meta(QuestionCategorySerializer.Meta):
        fields = (  # type: ignore[assignment]
            "id",
            "key",
            "name",
            "description",
            "generation_guidance",
            "sort_order",
            "applicable_subject_type_ids",
        )


class PublicQuestionTagSerializer(QuestionTagSerializer):
    class Meta(QuestionTagSerializer.Meta):
        fields = (  # type: ignore[assignment]
            "id",
            "key",
            "name",
            "description",
            "sort_order",
            "applicable_subject_type_ids",
        )


class QuestionCatalogQuerySerializer(StrictSerializer):
    status = serializers.ChoiceField(
        choices=("", *QuestionCategory.Status.values), required=False, default="", allow_blank=True
    )
    keyword = serializers.CharField(required=False, default="", allow_blank=True, max_length=150)
    subject_type_id = serializers.UUIDField(required=False, allow_null=True)


class PublicQuestionCatalogQuerySerializer(StrictSerializer):
    subject_type_id = serializers.UUIDField(required=False, allow_null=True)


class ApplicableSubjectTypesSerializer(StrictSerializer):
    applicable_subject_type_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list, max_length=100
    )

    def validate_applicable_subject_type_ids(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError("适用主体类型不能重复。")
        return value


class QuestionCategoryCreateSerializer(ApplicableSubjectTypesSerializer):
    key = serializers.CharField(max_length=100, trim_whitespace=False)
    name = serializers.CharField(max_length=150, trim_whitespace=False)
    description = serializers.CharField(
        required=False, default="", allow_blank=True, max_length=500, trim_whitespace=False
    )
    generation_guidance = serializers.CharField(
        required=False, default="", allow_blank=True, max_length=2000, trim_whitespace=False
    )
    sort_order = serializers.IntegerField(required=False, default=0, min_value=0)


class QuestionCategoryUpdateSerializer(ApplicableSubjectTypesSerializer):
    applicable_subject_type_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, max_length=100
    )
    expected_version = serializers.IntegerField(min_value=1)
    name = serializers.CharField(required=False, max_length=150, trim_whitespace=False)
    description = serializers.CharField(
        required=False, allow_blank=True, max_length=500, trim_whitespace=False
    )
    generation_guidance = serializers.CharField(
        required=False, allow_blank=True, max_length=2000, trim_whitespace=False
    )
    sort_order = serializers.IntegerField(required=False, min_value=0)

    def validate(self, attrs):
        if set(attrs) == {"expected_version"}:
            raise serializers.ValidationError({"non_field_errors": ["必须提供修改字段。"]})
        return attrs


class QuestionTagCreateSerializer(ApplicableSubjectTypesSerializer):
    key = serializers.CharField(max_length=100, trim_whitespace=False)
    name = serializers.CharField(max_length=150, trim_whitespace=False)
    description = serializers.CharField(
        required=False, default="", allow_blank=True, max_length=500, trim_whitespace=False
    )
    sort_order = serializers.IntegerField(required=False, default=0, min_value=0)


class QuestionTagUpdateSerializer(ApplicableSubjectTypesSerializer):
    applicable_subject_type_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, max_length=100
    )
    expected_version = serializers.IntegerField(min_value=1)
    name = serializers.CharField(required=False, max_length=150, trim_whitespace=False)
    description = serializers.CharField(
        required=False, allow_blank=True, max_length=500, trim_whitespace=False
    )
    sort_order = serializers.IntegerField(required=False, min_value=0)

    def validate(self, attrs):
        if set(attrs) == {"expected_version"}:
            raise serializers.ValidationError({"non_field_errors": ["必须提供修改字段。"]})
        return attrs


class ExpectedQuestionCatalogVersionSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
