from django.conf import settings
from rest_framework import serializers

from apps.admin_rbac.serializers import StrictSerializer

from .models import KeywordGenerationJob
from .taxonomy import KEYWORD_CATEGORY_VALUES, KEYWORD_INTENT_VALUES


class KeywordGenerationCreateSerializer(StrictSerializer):
    expected_subject_version_id = serializers.UUIDField()
    expected_keyword_set_version = serializers.IntegerField(min_value=0)
    target_count = serializers.IntegerField(min_value=1)
    include_short = serializers.BooleanField(default=False)
    include_long_tail = serializers.BooleanField(default=False)
    include_regional = serializers.BooleanField(default=False)
    regions = serializers.ListField(
        child=serializers.JSONField(),
        required=False,
        default=list,
    )
    generation_mode = serializers.ChoiceField(
        choices=KeywordGenerationJob.GenerationMode.values,
        required=False,
        default=KeywordGenerationJob.GenerationMode.SMART,
    )
    categories = serializers.ListField(
        child=serializers.ChoiceField(choices=sorted(KEYWORD_CATEGORY_VALUES)),
        required=False,
        default=list,
        max_length=14,
    )
    intents = serializers.ListField(
        child=serializers.ChoiceField(choices=sorted(KEYWORD_INTENT_VALUES)),
        required=False,
        default=list,
        max_length=8,
    )
    region_mode = serializers.ChoiceField(
        choices=KeywordGenerationJob.RegionMode.values,
        required=False,
        allow_null=True,
        default=None,
    )
    regenerate = serializers.BooleanField(default=False)

    def validate_target_count(self, value):
        if value > settings.KEYWORD_GENERATION_MAX_COUNT:
            raise serializers.ValidationError(
                "Keyword generation count exceeds the configured limit."
            )
        return value

    def validate_regions(self, value):
        if len(value) > settings.KEYWORD_GENERATION_MAX_REGIONS:
            raise serializers.ValidationError("Too many keyword generation regions.")
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if not attrs["include_short"] and not attrs["include_long_tail"]:
            raise serializers.ValidationError("At least one keyword length type is required.")
        if attrs["generation_mode"] == KeywordGenerationJob.GenerationMode.CUSTOM:
            if not attrs["categories"] or not attrs["intents"]:
                raise serializers.ValidationError(
                    "Custom keyword generation requires categories and intents."
                )
        if attrs["region_mode"] is None:
            attrs["region_mode"] = (
                KeywordGenerationJob.RegionMode.CUSTOM
                if attrs["include_regional"]
                else KeywordGenerationJob.RegionMode.UNRESTRICTED
            )
        if attrs["region_mode"] == KeywordGenerationJob.RegionMode.CUSTOM and not attrs["regions"]:
            raise serializers.ValidationError("Custom regions are required.")
        if (
            attrs["region_mode"] == KeywordGenerationJob.RegionMode.UNRESTRICTED
            and attrs["regions"]
        ):
            raise serializers.ValidationError("Unrestricted generation cannot include regions.")
        return attrs
