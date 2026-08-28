from rest_framework import serializers

from apps.admin_rbac.serializers import StrictSerializer

from .models import PaidMediaInquiry


class PaidMediaInquiryCreateSerializer(StrictSerializer):
    media_ids = serializers.ListField(
        child=serializers.CharField(max_length=128, trim_whitespace=True),
        allow_empty=False,
        max_length=200,
    )


class PaidMediaInquiryAdminUpdateSerializer(StrictSerializer):
    status = serializers.ChoiceField(
        choices=(
            PaidMediaInquiry.Status.CONTACTED,
            PaidMediaInquiry.Status.CANCELLED,
            PaidMediaInquiry.Status.COMPLETED,
        )
    )
    expected_version = serializers.IntegerField(min_value=1)


class PaidMediaInquirySerializer(serializers.ModelSerializer):
    subject_id = serializers.UUIDField(read_only=True)
    subject_name = serializers.SerializerMethodField()

    class Meta:
        model = PaidMediaInquiry
        fields = (
            "id",
            "subject_id",
            "subject_name",
            "selected_media",
            "item_count",
            "total_price",
            "status",
            "version",
            "created_at",
            "updated_at",
        )

    def get_subject_name(self, instance) -> str:
        version = getattr(instance.subject, "current_version", None)
        return version.official_name if version is not None else "未命名主体"


class PaidMediaInquiryAdminSerializer(PaidMediaInquirySerializer):
    user = serializers.SerializerMethodField()
    subject = serializers.SerializerMethodField()

    class Meta(PaidMediaInquirySerializer.Meta):
        fields = (
            "id",
            "user",
            "subject",
            "selected_media",
            "item_count",
            "total_price",
            "status",
            "version",
            "created_at",
            "updated_at",
        )

    def get_user(self, instance) -> dict[str, str]:
        return {
            "id": str(instance.user_id),
            "nickname": instance.user.nickname,
            "phone": instance.user.phone,
        }

    def get_subject(self, instance) -> dict[str, str]:
        version = getattr(instance.subject, "current_version", None)
        return {
            "id": str(instance.subject_id),
            "name": version.official_name if version is not None else "未命名主体",
        }
