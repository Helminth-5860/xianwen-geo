from rest_framework import serializers

from apps.admin_rbac.serializers import StrictSerializer

from .bank_models import QuestionFields


class QuestionGenerationCreateSerializer(StrictSerializer):
    distillation_set_id = serializers.UUIDField()
    expected_workspace_version = serializers.IntegerField(min_value=0)
    regenerate = serializers.BooleanField(default=False)


class QuestionDraftItemInputSerializer(StrictSerializer):
    text = serializers.CharField(max_length=1000, trim_whitespace=False)
    primary_category_id = serializers.UUIDField()
    tag_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    keyword_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    priority = serializers.ChoiceField(choices=QuestionFields.Priority.values)
    question_type = serializers.ChoiceField(choices=QuestionFields.QuestionType.values)
    participates_in_scoring = serializers.BooleanField()
    ai_reason = serializers.CharField(
        max_length=1000,
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        default="",
    )


class QuestionDraftSaveSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    items = QuestionDraftItemInputSerializer(many=True, allow_empty=False)


class QuestionBankConfirmSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)


class QuestionBankBulkRemoveSerializer(StrictSerializer):
    expected_version_id = serializers.UUIDField()
    question_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
        max_length=1000,
    )

    def validate_question_ids(self, values):
        if len(values) != len(set(values)):
            raise serializers.ValidationError("Question ids must be unique.")
        return values
