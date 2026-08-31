from typing import cast

from rest_framework import serializers

from apps.admin_rbac.risk_serializers import StrictPayloadSerializer
from apps.admin_rbac.serializers import StrictSerializer

from .models import Subscription, SubscriptionChange, SubscriptionChangeEvent, SubscriptionEvent


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
    confirmed = serializers.BooleanField(required=False, default=False)
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
    confirmed = serializers.BooleanField(required=False, default=False)
    plan_id = serializers.UUIDField()
    opening_note = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=500, trim_whitespace=False
    )


class TerminateSubscriptionRequestSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    confirmed = serializers.BooleanField(required=False, default=False)
    reason = serializers.CharField(max_length=500, trim_whitespace=False)


class SubscriptionEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionEvent
        fields = ("id", "event_type", "from_status", "to_status", "safe_summary", "created_at")


def entitlement_summary(snapshot):
    limits = snapshot.get("limits", {})
    models = snapshot.get("model_permissions", [])
    limit_keys = (
        sorted(limits)
        if isinstance(limits, dict)
        else sorted(
            cast(str, item.get("key"))
            for item in limits
            if isinstance(item, dict) and item.get("key")
        )
    )
    return {
        "valid_days": snapshot.get("valid_days"),
        "limit_keys": limit_keys,
        "max_models_per_detection": limits.get("max_models_per_detection"),
        "max_questions_per_detection": limits.get("max_questions_per_detection"),
        "enabled_model_keys": sorted(
            item.get("model_key")
            for item in models
            if isinstance(item, dict) and item.get("model_key")
        ),
    }


class CurrentSubscriptionSerializer(serializers.ModelSerializer):
    plan_code = serializers.CharField(source="plan.code")
    plan_name = serializers.CharField(source="plan.name")
    plan_price_display_mode = serializers.CharField(source="plan.price_display_mode")
    plan_display_price = serializers.DecimalField(
        source="plan.display_price", max_digits=12, decimal_places=2, allow_null=True
    )
    plan_display_currency = serializers.CharField(source="plan.display_currency")
    entitlement_summary = serializers.SerializerMethodField()

    class Meta:
        model = Subscription
        fields = (
            "id",
            "plan_id",
            "plan_code",
            "plan_name",
            "plan_price_display_mode",
            "plan_display_price",
            "plan_display_currency",
            "plan_version_id",
            "plan_version_no",
            "status",
            "source_type",
            "is_trial",
            "starts_at",
            "ends_at",
            "cycle_anchor_day",
            "cycle_anchor_time",
            "entitlement_summary",
            "version",
        )

    def get_entitlement_summary(self, obj):
        return entitlement_summary(obj.entitlement_snapshot)


class AdminSubscriptionListSerializer(CurrentSubscriptionSerializer):
    user_id = serializers.UUIDField()
    user_nickname = serializers.CharField(source="user.nickname")

    class Meta(CurrentSubscriptionSerializer.Meta):
        fields = (  # type: ignore[assignment]
            "id",
            "user_id",
            "user_nickname",
            "plan_id",
            "plan_code",
            "plan_name",
            "plan_price_display_mode",
            "plan_display_price",
            "plan_display_currency",
            "plan_version_id",
            "plan_version_no",
            "status",
            "source_type",
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
            "source_change_id",
            "cycle_anchor_day",
            "cycle_anchor_time",
            "activated_at",
            "expired_at",
            "terminated_at",
            "termination_reason",
            "entitlement_summary",
            "events",
            "created_at",
            "updated_at",
        )


class SubscriptionChangePreviewRequestSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    target_plan_version_id = serializers.UUIDField()
    change_type = serializers.ChoiceField(choices=SubscriptionChange.ChangeType.values)
    quota_policy = serializers.ChoiceField(choices=SubscriptionChange.QuotaPolicy.values)


class SubscriptionChangeRequestSerializer(SubscriptionChangePreviewRequestSerializer):
    confirmed = serializers.BooleanField(required=False, default=False)
    confirm_unavailable = serializers.BooleanField(required=False, default=False)
    unavailable_reason = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=500, trim_whitespace=False
    )
    reason = serializers.CharField(max_length=500, trim_whitespace=False)


class SubscriptionChangePayloadSerializer(StrictPayloadSerializer):
    target_plan_version_id = serializers.UUIDField()
    change_type = serializers.ChoiceField(choices=SubscriptionChange.ChangeType.values)
    quota_policy = serializers.ChoiceField(choices=SubscriptionChange.QuotaPolicy.values)
    confirm_unavailable = serializers.BooleanField(required=False, default=False)
    unavailable_reason = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=500, trim_whitespace=False
    )
    reason = serializers.CharField(max_length=500, trim_whitespace=False)
    idempotency_key_version = serializers.IntegerField(min_value=1)
    idempotency_key_digest = serializers.RegexField(r"^[0-9a-f]{64}$")
    idempotency_scope_digest = serializers.RegexField(r"^[0-9a-f]{64}$")
    request_digest = serializers.RegexField(r"^[0-9a-f]{64}$")


class CancelSubscriptionChangeRequestSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    confirmed = serializers.BooleanField(required=False, default=False)
    reason = serializers.CharField(max_length=500, trim_whitespace=False)


class CancelSubscriptionChangePayloadSerializer(StrictPayloadSerializer):
    reason = serializers.CharField(max_length=500, trim_whitespace=False)
    idempotency_key_version = serializers.IntegerField(min_value=1)
    idempotency_key_digest = serializers.RegexField(r"^[0-9a-f]{64}$")
    idempotency_scope_digest = serializers.RegexField(r"^[0-9a-f]{64}$")
    request_digest = serializers.RegexField(r"^[0-9a-f]{64}$")


class SubscriptionChangeEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionChangeEvent
        fields = ("id", "event_type", "from_status", "to_status", "safe_summary", "created_at")


class UserSubscriptionChangeSerializer(serializers.ModelSerializer):
    target_plan_name = serializers.CharField(source="target_plan.name")
    target_plan_version_no = serializers.IntegerField()

    class Meta:
        model = SubscriptionChange
        fields = (
            "id",
            "from_subscription_id",
            "target_plan_id",
            "target_plan_name",
            "target_plan_version_no",
            "status",
            "change_type",
            "quota_policy",
            "effective_at",
            "executed_at",
            "cancelled_at",
            "failed_at",
            "stable_error_code",
            "created_at",
            "version",
        )


class AdminSubscriptionChangeSerializer(UserSubscriptionChangeSerializer):
    user_id = serializers.UUIDField()
    user_nickname = serializers.CharField(source="user.nickname")
    events = SubscriptionChangeEventSerializer(many=True, read_only=True)

    class Meta(UserSubscriptionChangeSerializer.Meta):
        fields = (  # type: ignore[assignment]
            *UserSubscriptionChangeSerializer.Meta.fields,
            "user_id",
            "user_nickname",
            "target_plan_version_id",
            "reason",
            "unavailable_reason",
            "requested_by_id",
            "cancellation_reason",
            "next_attempt_at",
            "retry_count",
            "events",
            "updated_at",
        )
