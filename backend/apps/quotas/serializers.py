from rest_framework import serializers

from apps.admin_rbac.risk_serializers import StrictPayloadSerializer
from apps.admin_rbac.serializers import StrictSerializer
from apps.users.validators import validate_safe_plain_text

from .catalog import QUOTA_BY_KEY
from .models import QuotaAccount, QuotaLedgerEntry


class QuotaAdjustmentRequestSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    amount = serializers.IntegerField(min_value=1, max_value=2**63 - 1)
    confirmed = serializers.BooleanField(required=False, default=False)
    current_password = serializers.CharField(
        max_length=128, required=False, default="", write_only=True, trim_whitespace=False
    )
    reason = serializers.CharField(max_length=500, trim_whitespace=False)

    def validate_reason(self, value):
        return validate_safe_plain_text(
            value, field_label="\u989d\u5ea6\u8c03\u6574\u539f\u56e0", max_length=500, required=True
        )


class QuotaAdjustmentPayloadSerializer(StrictPayloadSerializer):
    amount = serializers.IntegerField(min_value=1, max_value=2**63 - 1)
    reason = serializers.CharField(max_length=500, trim_whitespace=False)
    idempotency_key_version = serializers.IntegerField(min_value=1, max_value=1)
    idempotency_key_digest = serializers.RegexField(r"^[0-9a-f]{64}$")
    idempotency_scope_digest = serializers.RegexField(r"^[0-9a-f]{64}$")
    request_digest = serializers.RegexField(r"^[0-9a-f]{64}$")

    def validate_reason(self, value):
        return validate_safe_plain_text(
            value, field_label="\u989d\u5ea6\u8c03\u6574\u539f\u56e0", max_length=500, required=True
        )


class UserQuotaAccountSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()

    class Meta:
        model = QuotaAccount
        fields = (
            "id",
            "quota_type",
            "display_name",
            "unit",
            "scope",
            "entitlement_amount",
            "available",
            "frozen",
            "cycle_started_at",
            "cycle_ends_at",
            "version",
        )

    def get_display_name(self, obj):
        names = {
            "detection_points": "\u68c0\u6d4b\u70b9\u6570",
            "article_credits": "\u6587\u7ae0\u989d\u5ea6",
            "image_credits": "\u56fe\u7247\u989d\u5ea6",
            "storage_bytes": "\u5b58\u50a8\u7a7a\u95f4",
            "assistant_messages": "AI \u52a9\u624b\u6d88\u606f",
        }
        return names.get(obj.quota_type, obj.quota_type)


class UserQuotaLedgerSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuotaLedgerEntry
        fields = (
            "id",
            "account_id",
            "quota_type",
            "sequence",
            "action",
            "available_delta",
            "available_after",
            "frozen_delta",
            "frozen_after",
            "created_at",
        )


class AdminQuotaAccountSerializer(UserQuotaAccountSerializer):
    user_id = serializers.UUIDField()
    user_nickname = serializers.CharField(source="user.nickname")
    subscription_id = serializers.UUIDField()
    last_ledger_entry_id = serializers.UUIDField(allow_null=True)

    class Meta:
        model = QuotaAccount
        fields = (
            "id",
            "user_id",
            "user_nickname",
            "subscription_id",
            "quota_type",
            "unit",
            "scope",
            "entitlement_amount",
            "available",
            "frozen",
            "cycle_started_at",
            "cycle_ends_at",
            "ledger_sequence",
            "last_ledger_entry_id",
            "version",
            "created_at",
            "updated_at",
        )


class AdminQuotaLedgerSerializer(serializers.ModelSerializer):
    actor_id = serializers.UUIDField(allow_null=True)

    class Meta:
        model = QuotaLedgerEntry
        fields = (
            "id",
            "account_id",
            "user_id",
            "subscription_id",
            "quota_type",
            "sequence",
            "action",
            "available_before",
            "available_delta",
            "available_after",
            "frozen_before",
            "frozen_delta",
            "frozen_after",
            "account_version_before",
            "account_version_after",
            "business_type",
            "safe_reason",
            "actor_id",
            "request_id",
            "created_at",
        )


def validate_quota_type(value):
    if value not in QUOTA_BY_KEY or QUOTA_BY_KEY[value].subject_level:
        raise serializers.ValidationError("\u989d\u5ea6\u7c7b\u578b\u4e0d\u6b63\u786e\u3002")
    return value
