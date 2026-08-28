from rest_framework import serializers

from .models import AutoPublishPolicy


class AutoPublishPolicySerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    operating_mode = serializers.ChoiceField(choices=AutoPublishPolicy.OperatingMode.values)
    distribution_strategy = serializers.ChoiceField(
        choices=AutoPublishPolicy.DistributionStrategy.values
    )
    custom_platform_keys = serializers.ListField(
        child=serializers.CharField(max_length=50), required=False, allow_empty=True
    )
    frequency_mode = serializers.ChoiceField(choices=AutoPublishPolicy.FrequencyMode.values)
    custom_daily_limit = serializers.IntegerField(min_value=1, max_value=20)
    image_strategy = serializers.ChoiceField(choices=AutoPublishPolicy.ImageStrategy.values)
    image_richness = serializers.ChoiceField(choices=AutoPublishPolicy.ImageRichness.values)
    expected_version = serializers.IntegerField(min_value=1)


class AuthorizationStartSerializer(serializers.Serializer):
    platform_key = serializers.CharField(max_length=50)
    credentials = serializers.DictField(required=False, default=dict, write_only=True)


class AccountParticipationSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    expected_version = serializers.IntegerField(min_value=1)


class PublicationJobCreateSerializer(serializers.Serializer):
    article_id = serializers.UUIDField()
