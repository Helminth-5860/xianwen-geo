from rest_framework import serializers

from apps.admin_rbac.serializers import StrictSerializer


class PublicationVerificationCreateSerializer(StrictSerializer):
    url = serializers.URLField(max_length=4096)


class PublicationVerificationBulkDeleteSerializer(StrictSerializer):
    ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
        max_length=100,
    )

    def validate_ids(self, values):
        if len(values) != len(set(values)):
            raise serializers.ValidationError("ids must be unique")
        return values
