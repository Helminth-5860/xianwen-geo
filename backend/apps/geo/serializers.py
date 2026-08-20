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
