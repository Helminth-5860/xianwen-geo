from rest_framework import serializers

from apps.admin_rbac.serializers import StrictSerializer

from .models import PlanApplication, PlanApplicationEvent


def mask_phone(phone: str) -> str:
    return f"{phone[:3]}****{phone[-4:]}"


class PlanApplicationCreateSerializer(StrictSerializer):
    plan_id = serializers.UUIDField()
    plan_version_id = serializers.UUIDField()
    user_note = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=500, trim_whitespace=False
    )


class PlanApplicationCancelSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)


class PlanApplicationAdminActionSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    confirmed = serializers.BooleanField(required=False, default=False)
    current_password = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=128,
        trim_whitespace=False,
        write_only=True,
    )


class PlanApplicationEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanApplicationEvent
        fields = ("id", "event_type", "from_status", "to_status", "safe_summary", "created_at")


class PlanApplicationUserSerializer(serializers.ModelSerializer):
    events = PlanApplicationEventSerializer(many=True, read_only=True)

    class Meta:
        model = PlanApplication
        fields = (
            "id",
            "plan_id",
            "requested_plan_version_id",
            "requested_version_no",
            "public_plan_snapshot",
            "status",
            "source",
            "user_note",
            "contacted_at",
            "closed_at",
            "cancelled_at",
            "version",
            "created_at",
            "updated_at",
            "events",
        )


class PlanApplicationAdminListSerializer(serializers.ModelSerializer):
    applicant_id = serializers.UUIDField()
    applicant_nickname = serializers.CharField(source="applicant.nickname")
    applicant_phone_masked = serializers.SerializerMethodField()
    current_owner = serializers.SerializerMethodField()

    class Meta:
        model = PlanApplication
        fields: tuple[str, ...] = (
            "id",
            "applicant_id",
            "applicant_nickname",
            "applicant_phone_masked",
            "plan_id",
            "requested_plan_version_id",
            "requested_version_no",
            "status",
            "current_owner",
            "version",
            "created_at",
            "updated_at",
        )

    def get_applicant_phone_masked(self, obj):
        return mask_phone(obj.applicant.phone)

    def get_current_owner(self, obj):
        try:
            profile = obj.applicant.customer_assignment.owner_admin
        except Exception:
            return None
        if profile is None:
            return None
        return {"id": str(profile.pk), "nickname": profile.user.nickname}


class PlanApplicationAdminDetailSerializer(PlanApplicationAdminListSerializer):
    applicant_phone = serializers.CharField(source="applicant.phone")
    public_plan_snapshot = serializers.JSONField()
    events = PlanApplicationEventSerializer(many=True, read_only=True)

    class Meta(PlanApplicationAdminListSerializer.Meta):
        fields: tuple[str, ...] = (
            *PlanApplicationAdminListSerializer.Meta.fields,
            "applicant_phone",
            "public_plan_snapshot",
            "user_note",
            "contacted_at",
            "contacted_by_id",
            "closed_at",
            "closed_by_id",
            "cancelled_at",
            "events",
        )
