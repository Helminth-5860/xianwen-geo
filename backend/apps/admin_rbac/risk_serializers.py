from rest_framework import serializers

from apps.users.validators import validate_safe_plain_text

from .models import ApprovalRequest, AuditEvent, RiskAction, RiskPolicy
from .security import normalize_network


class StrictPayloadSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({key: ["不允许的字段。"] for key in sorted(unknown)})
        return super().to_internal_value(data)


class EmptyPayloadSerializer(StrictPayloadSerializer):
    pass


class AdminRoleChangePayloadSerializer(StrictPayloadSerializer):
    role_id = serializers.UUIDField()


class RolePermissionsPayloadSerializer(StrictPayloadSerializer):
    permission_keys = serializers.ListField(
        child=serializers.CharField(max_length=100), allow_empty=True, max_length=200
    )


class RoleSecurityPayloadSerializer(StrictPayloadSerializer):
    require_sms_2fa = serializers.BooleanField(required=False)
    ip_allowlist_enabled = serializers.BooleanField(required=False)
    confirm_lockout = serializers.BooleanField(default=False, required=False)


class IpAllowlistPayloadSerializer(StrictPayloadSerializer):
    operation = serializers.ChoiceField(choices=("policy", "create", "update"))
    entry_id = serializers.UUIDField(required=False)
    ip_allowlist_enabled = serializers.BooleanField(required=False)
    network_cidr = serializers.CharField(max_length=64, required=False, trim_whitespace=False)
    label = serializers.CharField(  # type: ignore[assignment]
        max_length=100, required=False, allow_blank=True, default=""
    )
    status = serializers.ChoiceField(choices=("active", "inactive"), required=False)
    confirm_lockout = serializers.BooleanField(default=False, required=False)

    def validate_network_cidr(self, value):
        try:
            return normalize_network(value)[0]
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def validate_label(self, value):
        return validate_safe_plain_text(
            value, field_label="白名单标签", max_length=100, required=False
        )

    def validate(self, attrs):
        operation = attrs["operation"]
        allowed_fields = {
            "policy": {"operation", "ip_allowlist_enabled", "confirm_lockout"},
            "create": {"operation", "network_cidr", "label", "confirm_lockout"},
            "update": {"operation", "entry_id", "status", "label", "confirm_lockout"},
        }[operation]
        unexpected = set(self.initial_data) - allowed_fields
        if unexpected:
            raise serializers.ValidationError(
                {key: ["该操作不允许此字段。"] for key in sorted(unexpected)}
            )
        if operation == "create" and "network_cidr" not in attrs:
            raise serializers.ValidationError({"network_cidr": ["创建时必须提供。"]})
        if operation == "policy" and "ip_allowlist_enabled" not in attrs:
            raise serializers.ValidationError({"ip_allowlist_enabled": ["策略更新时必须提供。"]})
        if operation == "update" and ("entry_id" not in attrs or "status" not in attrs):
            raise serializers.ValidationError({"entry_id": ["更新时必须提供条目和状态。"]})
        return {key: value for key, value in attrs.items() if key in allowed_fields}


class CustomerAssignmentPayloadSerializer(StrictPayloadSerializer):
    owner_admin_id = serializers.UUIDField(allow_null=True)
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True)

    def validate_reason(self, value):
        return validate_safe_plain_text(
            value, field_label="归属变更原因", max_length=200, required=False
        )


class ReasonPayloadSerializer(StrictPayloadSerializer):
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)

    def validate_reason(self, value):
        return validate_safe_plain_text(
            value, field_label="操作原因", max_length=500, required=False
        )


class RejectUserPayloadSerializer(ReasonPayloadSerializer):
    reason = serializers.CharField(max_length=500, allow_blank=False)

    def validate_reason(self, value):
        return validate_safe_plain_text(
            value, field_label="拒绝原因", max_length=500, required=True
        )


class RiskActionSerializer(serializers.ModelSerializer):
    current_mode = serializers.CharField(source="policy.current_mode")
    policy_version = serializers.IntegerField(source="policy.version")

    class Meta:
        model = RiskAction
        fields = (
            "key",
            "name",
            "module",
            "target_type",
            "supported_modes",
            "default_mode",
            "minimum_mode",
            "status",
            "catalog_version",
            "current_mode",
            "policy_version",
        )


class RiskPolicySerializer(serializers.ModelSerializer):
    action_key = serializers.CharField(source="action_id")
    supported_modes = serializers.JSONField(source="action.supported_modes")
    default_mode = serializers.CharField(source="action.default_mode")
    minimum_mode = serializers.CharField(source="action.minimum_mode")

    class Meta:
        model = RiskPolicy
        fields = (
            "action_key",
            "current_mode",
            "version",
            "supported_modes",
            "default_mode",
            "minimum_mode",
            "updated_at",
        )


class RiskPolicyUpdateSerializer(StrictPayloadSerializer):
    current_mode = serializers.ChoiceField(choices=("confirm", "password", "two_person"))
    expected_version = serializers.IntegerField(min_value=1)
    current_password = serializers.CharField(max_length=128, write_only=True, trim_whitespace=False)
    confirmed = serializers.BooleanField()


class ApprovalSerializer(serializers.ModelSerializer):
    requester_id = serializers.UUIDField()
    approved_by_id = serializers.UUIDField(allow_null=True)
    rejected_by_id = serializers.UUIDField(allow_null=True)

    class Meta:
        model = ApprovalRequest
        fields = (
            "id",
            "action_key",
            "policy_version",
            "requester_id",
            "target_type",
            "target_id",
            "target_version",
            "safe_summary",
            "status",
            "expires_at",
            "approved_by_id",
            "approved_at",
            "rejected_by_id",
            "rejected_at",
            "rejection_reason",
            "cancelled_at",
            "executed_at",
            "execution_result",
            "stable_error_code",
            "request_id",
            "created_at",
            "updated_at",
        )


class ApprovalApproveSerializer(StrictPayloadSerializer):
    current_password = serializers.CharField(max_length=128, write_only=True, trim_whitespace=False)


class ApprovalRejectSerializer(StrictPayloadSerializer):
    reason = serializers.CharField(max_length=500, trim_whitespace=False)

    def validate_reason(self, value):
        return validate_safe_plain_text(
            value, field_label="拒绝原因", max_length=500, required=True
        )


class AuditEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditEvent
        fields = (
            "id",
            "category",
            "action_key",
            "outcome",
            "actor_id",
            "subject_id",
            "requester_id",
            "approver_id",
            "target_type",
            "target_id",
            "request_id",
            "approval_request_id",
            "safe_before",
            "safe_after",
            "stable_error_code",
            "ip_fingerprint",
            "user_agent_digest",
            "created_at",
        )
