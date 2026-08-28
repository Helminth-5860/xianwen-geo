from rest_framework import serializers

from .models import PublishingPreference


class PublishingPreferenceSerializer(serializers.Serializer):
    is_enabled = serializers.BooleanField(required=False)
    mode = serializers.ChoiceField(choices=PublishingPreference.Mode.choices, required=False)
    distribution_strategy = serializers.ChoiceField(
        choices=PublishingPreference.DistributionStrategy.choices,
        required=False,
    )
    custom_platform_keys = serializers.ListField(
        child=serializers.CharField(max_length=32), required=False, allow_empty=True
    )
    image_strategy = serializers.ChoiceField(
        choices=PublishingPreference.ImageStrategy.choices,
        required=False,
    )
    image_density = serializers.ChoiceField(
        choices=PublishingPreference.ImageDensity.choices,
        required=False,
    )
    frequency_mode = serializers.ChoiceField(
        choices=PublishingPreference.FrequencyMode.choices,
        required=False,
    )
    posts_per_day = serializers.IntegerField(min_value=1, max_value=10, required=False)
    expected_version = serializers.IntegerField(min_value=1, required=False)


class AuthorizationStartSerializer(serializers.Serializer):
    platform_key = serializers.CharField(max_length=32)


class PlatformToggleSerializer(serializers.Serializer):
    enabled_for_auto = serializers.BooleanField()


class PublicationCreateSerializer(serializers.Serializer):
    article_id = serializers.UUIDField()
    platform_keys = serializers.ListField(
        child=serializers.CharField(max_length=32), required=False, allow_empty=False
    )
    scheduled_at = serializers.DateTimeField(required=False, allow_null=True)
