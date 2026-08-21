from rest_framework import serializers

from apps.admin_rbac.serializers import StrictSerializer


class GeoDetectionSelectionSerializer(StrictSerializer):
    question_ids = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=False, max_length=10000
    )
    model_ids = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=False, max_length=8
    )
    mode = serializers.ChoiceField(choices=("new",), default="new")

    def validate_question_ids(self, values):
        if len(values) != len(set(values)):
            raise serializers.ValidationError("question_ids must be unique")
        return values

    def validate_model_ids(self, values):
        if len(values) != len(set(values)):
            raise serializers.ValidationError("model_ids must be unique")
        return values


class ReportExportSerializer(StrictSerializer):
    format = serializers.ChoiceField(choices=("pdf", "word", "excel"))


class AdjustedRetestSerializer(GeoDetectionSelectionSerializer):
    mode = serializers.ChoiceField(choices=("new",), default="new", required=False)


class GeoRetestSerializer(StrictSerializer):
    mode = serializers.ChoiceField(choices=("quick", "adjusted"))
    question_ids = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=False, required=False
    )
    model_ids = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=False, required=False
    )

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if attrs["mode"] == "quick" and ("question_ids" in attrs or "model_ids" in attrs):
            raise serializers.ValidationError(
                "quick retest always uses baseline questions and models"
            )
        if attrs["mode"] == "adjusted" and not {
            "question_ids",
            "model_ids",
        }.issubset(attrs):
            raise serializers.ValidationError("adjusted retest requires question_ids and model_ids")
        for field in ("question_ids", "model_ids"):
            values = attrs.get(field, [])
            if len(values) != len(set(values)):
                raise serializers.ValidationError(f"{field} must be unique")
        return attrs


class StrategyCreateSerializer(StrictSerializer):
    period = serializers.ChoiceField(choices=("7d", "30d", "90d", "custom"))
    custom_days = serializers.IntegerField(min_value=1, max_value=365, required=False)
    regenerate = serializers.BooleanField(default=False)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if attrs["period"] == "custom" and "custom_days" not in attrs:
            raise serializers.ValidationError("custom_days is required for a custom period")
        if attrs["period"] != "custom" and "custom_days" in attrs:
            raise serializers.ValidationError("custom_days is only valid for a custom period")
        return attrs


class StrategyNoteSerializer(StrictSerializer):
    text = serializers.CharField(max_length=10_000, allow_blank=True, trim_whitespace=False)
    expected_version = serializers.IntegerField(min_value=0)


class StrategyNoteDeleteSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)


class AssistantMessageSerializer(StrictSerializer):
    role = serializers.ChoiceField(choices=("user", "assistant"))
    content = serializers.CharField(max_length=2000, trim_whitespace=True)


class AssistantRespondSerializer(StrictSerializer):
    subject_id = serializers.UUIDField()
    messages = AssistantMessageSerializer(many=True, allow_empty=False)

    def validate_messages(self, values):
        if len(values) > 12:
            raise serializers.ValidationError("messages must contain at most 12 items")
        return values
