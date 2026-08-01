from rest_framework import serializers

from apps.admin_rbac.risk_serializers import StrictPayloadSerializer
from apps.admin_rbac.serializers import StrictSerializer

from .models import Subscription, SubscriptionEvent


class OpenSubscriptionPayloadSerializer(StrictPayloadSerializer):
    selected_plan_version_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    confirm_unavailable = serializers.BooleanField(required=False, default=False)
    unavailable_reason = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=500, trim_whitespace=False
    )
    confirm_version_override = serializers.BooleanField(required=False, default=False)
    override_reason = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=500, trim_whitespace=False
    )
    opening_note = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=500, trim_whitespace=False
    )


class GrantTrialPayloadSerializer(StrictPayloadSerializer):
    plan_id = serializers.UUIDField()
    opening_note = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=500, trim_whitespace=False
    )


class TerminateSubscriptionPayloadSerializer(StrictPayloadSerializer):
    reason = serializers.CharField(max_length=500, trim_whitespace=False)


class OpenSubscriptionRequestSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    selected_plan_version_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    confirm_unavailable = serializers.BooleanField(required=False, default=False)
    unavailable_reason = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=500, trim_whitespace=False
    )
    confirm_version_override = serializers.BooleanField(required=False, default=False)
    override_reason = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=500, trim_whitespace=False
    )
    opening_note = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=500, trim_whitespace=False
    )


class GrantTrialRequestSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    plan_id = serializers.UUIDField()
    opening_note = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=500, trim_whitespace=False
    )


class TerminateSubscriptionRequestSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=500, trim_whitespace=False)


class SubscriptionEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionEvent
        fields = ("id", "event_type", "from_status", "to_status", "safe_summary", "created_at")


def entitlement_summary(snapshot):
    limits = snapshot.get("limits", [])
    models = snapshot.get("model_permissions", [])
    return {
        "valid_days": snapshot.get("valid_days"),
        "limit_keys": sorted(
            item.get("key") for item in limits if isinstance(item, dict) and item.get("key")
        ),
        "enabled_model_keys": sorted(
            item.get("model_key")
            for item in models
            if isinstance(item, dict) and item.get("enabled") and item.get("model_key")
        ),
    }


class CurrentSubscriptionSerializer(serializers.ModelSerializer):
    plan_code = serializers.CharField(source="plan.code")
    plan_name = serializers.CharField(source="plan.name")
    entitlement_summary = serializers.SerializerMethodField()

    class Meta:
        model = Subscription
        fields = (
            "id",
            "plan_id",
            "plan_code",
            "plan_name",
            "plan_version_id",
            "plan_version_no",
            "status",
            "is_trial",
            "starts_at",
            "ends_at",
            "cycle_anchor_day",
            "entitlement_summary",
            "version",
        )

    def get_entitlement_summary(self, obj):
        return entitlement_summary(obj.entitlement_snapshot)


class AdminSubscriptionListSerializer(CurrentSubscriptionSerializer):
    user_id = serializers.UUIDField()
    user_nickname = serializers.CharField(source="user.nickname")

    class Meta(CurrentSubscriptionSerializer.Meta):
        fields = (
            "id",
            "user_id",
            "user_nickname",
            "plan_id",
            "plan_code",
            "plan_name",
            "plan_version_id",
            "plan_version_no",
            "status",
            "is_trial",
            "starts_at",
            "ends_at",
            "version",
        )


class AdminSubscriptionDetailSerializer(AdminSubscriptionListSerializer):
    events = SubscriptionEventSerializer(many=True, read_only=True)

    class Meta(AdminSubscriptionListSerializer.Meta):
        fields = (  # type: ignore[assignment]
            *AdminSubscriptionListSerializer.Meta.fields,
            "source_application_id",
            "cycle_anchor_day",
            "activated_at",
            "expired_at",
            "terminated_at",
            "termination_reason",
            "entitlement_summary",
            "events",
            "created_at",
            "updated_at",
        )
