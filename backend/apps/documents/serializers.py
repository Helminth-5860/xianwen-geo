from rest_framework import serializers

from apps.admin_rbac.serializers import StrictSerializer

from .models import FileUploadIntent, UserDocument


class UploadIntentCreateSerializer(StrictSerializer):
    subject_id = serializers.UUIDField()
    filename = serializers.CharField(min_length=1, max_length=255)
    content_type = serializers.CharField(min_length=1, max_length=127)
    size_bytes = serializers.IntegerField(min_value=1)
    purpose = serializers.ChoiceField(
        choices=FileUploadIntent.Purpose.choices,
        default=FileUploadIntent.Purpose.SUBJECT_LIBRARY,
    )


class UploadIntentCompleteSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)


class UploadIntentSerializer(serializers.ModelSerializer):
    document_id = serializers.SerializerMethodField()
    document_version_id = serializers.UUIDField(source="completed_version_id", allow_null=True)

    class Meta:
        model = FileUploadIntent
        fields = (
            "id",
            "status",
            "version",
            "declared_filename",
            "declared_file_kind",
            "declared_size",
            "expires_at",
            "stable_error_code",
            "document_id",
            "document_version_id",
            "created_at",
            "updated_at",
        )

    def get_document_id(self, obj):
        return obj.completed_version.document_id if obj.completed_version_id else None


class UserDocumentSerializer(serializers.ModelSerializer):
    document_version_id = serializers.UUIDField(source="current_version_id")
    detected_file_kind = serializers.CharField(source="current_version.detected_file_kind")
    size_bytes = serializers.IntegerField(source="current_version.size_bytes")
    safe_status = serializers.SerializerMethodField()
    download_available = serializers.SerializerMethodField()

    class Meta:
        model = UserDocument
        fields = (
            "id",
            "document_version_id",
            "display_name",
            "purpose",
            "detected_file_kind",
            "size_bytes",
            "safe_status",
            "download_available",
            "created_at",
        )

    def get_safe_status(self, obj):
        return "clean"

    def get_download_available(self, obj):
        return obj.current_version_id is not None
