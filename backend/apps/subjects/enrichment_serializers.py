from django.conf import settings
from rest_framework import serializers

from apps.admin_rbac.serializers import StrictSerializer


class SubjectEnrichmentSourceRefSerializer(StrictSerializer):
    source_type = serializers.ChoiceField(choices=("document", "web"))
    parsed_version_id = serializers.UUIDField()


class SubjectEnrichmentCreateSerializer(StrictSerializer):
    expected_subject_version = serializers.IntegerField(min_value=1)
    sources = SubjectEnrichmentSourceRefSerializer(
        many=True,
        allow_empty=False,
    )
    target_field_keys = serializers.ListField(
        child=serializers.CharField(max_length=64),
        allow_empty=False,
        max_length=20,
    )

    def validate_sources(self, value):
        if len(value) > settings.SUBJECT_ENRICHMENT_MAX_SOURCES:
            raise serializers.ValidationError("Too many enrichment sources.")
        return value


class SubjectEnrichmentDecisionSerializer(StrictSerializer):
    suggestion_id = serializers.UUIDField()
    accepted = serializers.BooleanField()


class SubjectEnrichmentConfirmSerializer(StrictSerializer):
    expected_subject_version = serializers.IntegerField(min_value=1)
    expected_job_version = serializers.IntegerField(min_value=1)
    decisions = SubjectEnrichmentDecisionSerializer(
        many=True,
        allow_empty=False,
    )

    def validate_decisions(self, value):
        if len(value) > settings.SUBJECT_ENRICHMENT_MAX_TARGET_FIELDS:
            raise serializers.ValidationError("Too many enrichment decisions.")
        return value
