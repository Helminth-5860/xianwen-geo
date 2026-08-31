from rest_framework import serializers

from .serializers import StrictSerializer


class SalesContactUploadSerializer(StrictSerializer):
    qr_code = serializers.FileField(required=True, allow_empty_file=False)
    enabled = serializers.BooleanField(required=False, default=True)


class SalesContactEnabledSerializer(StrictSerializer):
    enabled = serializers.BooleanField(required=True)
