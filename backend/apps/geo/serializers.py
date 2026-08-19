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
