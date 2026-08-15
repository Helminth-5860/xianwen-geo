from django.conf import settings
from rest_framework import serializers

from apps.admin_rbac.serializers import StrictSerializer


class KeywordGenerationCreateSerializer(StrictSerializer):
    expected_subject_version_id = serializers.UUIDField()
    expected_keyword_set_version = serializers.IntegerField(min_value=0)
    target_count = serializers.IntegerField(min_value=1)
    include_short = serializers.BooleanField(default=False)
    include_long_tail = serializers.BooleanField(default=False)
    include_regional = serializers.BooleanField(default=False)
    regions = serializers.ListField(
        child=serializers.CharField(
            max_length=200,
            trim_whitespace=False,
        ),
        required=False,
        default=list,
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
