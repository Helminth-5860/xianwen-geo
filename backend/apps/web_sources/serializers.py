from rest_framework import serializers

from apps.admin_rbac.serializers import StrictSerializer

from .models import WebSourceImport


class WebSourceImportRequestSerializer(StrictSerializer):
    subject_id = serializers.UUIDField()
    url = serializers.CharField(max_length=4096, trim_whitespace=False)


class WebSourceConfirmSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    source_parsed_version_id = serializers.UUIDField()
    confirmed_text = serializers.CharField(allow_blank=True, trim_whitespace=False)


class WebSourceImportSerializer(serializers.ModelSerializer):
    latest_version = serializers.SerializerMethodField()
    current_confirmed_version = serializers.SerializerMethodField()

    class Meta:
        model = WebSourceImport
        fields = (
            "id",
            "subject_id",
            "display_url",
            "has_query",
            "status",
            "stable_error_code",
            "version",
            "latest_version",
            "current_confirmed_version",
            "created_at",
            "updated_at",
        )

    def get_latest_version(self, obj):
        value = obj.latest_parsed_version
        if value is None:
            return None
        return {
            "id": str(value.pk),
            "version_no": value.version_no,
            "canonical_text": value.canonical_text,
        }

    def get_current_confirmed_version(self, obj):
        value = obj.current_confirmed_version
        if value is None:
            return None
        return {"id": str(value.pk), "version_no": value.version_no}
