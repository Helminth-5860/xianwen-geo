from rest_framework import serializers

from .sensitive_audit_models import SensitiveAuditLog


class SensitiveAuditLogListSerializer(serializers.ModelSerializer):
    class Meta:
        model = SensitiveAuditLog
        fields = (
            "id",
            "action_key",
            "outcome",
            "channel",
            "actor_user_id_snapshot",
            "actor_name_snapshot",
            "actor_role_snapshot",
            "actor_tenant_id_snapshot",
            "actor_tenant_name_snapshot",
            "target_user_id_snapshot",
            "target_name_snapshot",
            "target_tenant_id_snapshot",
            "target_tenant_name_snapshot",
            "quota_type",
            "quota_before",
            "quota_requested_delta",
            "quota_delta",
            "quota_after",
            "ledger_entry_id",
            "request_id",
            "operation_ip",
            "login_ip_snapshot",
            "safe_reason",
            "failure_reason",
            "created_at",
        )


class SensitiveAuditLogDetailSerializer(SensitiveAuditLogListSerializer):
    class Meta(SensitiveAuditLogListSerializer.Meta):
        fields = (*SensitiveAuditLogListSerializer.Meta.fields, "user_agent", "details")
