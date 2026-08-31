from rest_framework import serializers

from apps.admin_rbac.risk_serializers import StrictPayloadSerializer
from apps.admin_rbac.serializers import StrictSerializer
from apps.users.validators import validate_safe_plain_text

from .catalog import QUOTA_BY_KEY
from .models import QuotaAccount, QuotaLedgerEntry

QUOTA_DISPLAY_NAMES = {
    "geo_detection_runs": "GEO 综合检测",
    "article_generations": "文章生成",
    "auto_publish_count": "自动发文",
    "image_generations": "图片生成",
    "source_index_scans": "信源指数扫描",
    "negative_index_scans": "负面信息扫描",
    "website_audits": "官网检测",
    "website_generations": "官网生成",
    "video_script_generations": "视频脚本生成",
    "competitor_comparisons": "竞品对比",
    "keyword_generated_items": "关键词生成",
    "question_generated_items": "问题生成",
}

UNIT_DISPLAY_NAMES = {
    "run": "次",
    "article": "篇",
    "image": "张",
    "item": "条",
}

LEDGER_ACTION_NAMES = {
    QuotaLedgerEntry.Action.INITIALIZE: "套餐额度到账",
    QuotaLedgerEntry.Action.STORAGE_CAPACITY_RECONCILE: "额度校准",
    QuotaLedgerEntry.Action.FREEZE: "任务处理中",
    QuotaLedgerEntry.Action.CONSUME: "任务已完成",
    QuotaLedgerEntry.Action.RELEASE: "任务额度已恢复",
    QuotaLedgerEntry.Action.GRANT: "额度增加",
    QuotaLedgerEntry.Action.COMPENSATE: "额度补充",
    QuotaLedgerEntry.Action.REFUND: "额度返还",
    QuotaLedgerEntry.Action.MANUAL_DEDUCT: "额度扣减",
    QuotaLedgerEntry.Action.PLAN_CHANGE_FORFEIT: "套餐变更调整",
    QuotaLedgerEntry.Action.PLAN_CHANGE_TRANSFER_OUT: "套餐变更转出",
    QuotaLedgerEntry.Action.PLAN_CHANGE_TRANSFER_IN: "套餐变更转入",
    QuotaLedgerEntry.Action.CYCLE_FORFEIT: "周期额度更新",
    QuotaLedgerEntry.Action.CYCLE_LATE_RELEASE_FORFEIT: "周期额度更新",
    QuotaLedgerEntry.Action.EXPIRY_FORFEIT: "套餐到期调整",
    QuotaLedgerEntry.Action.EXPIRY_LATE_RELEASE_FORFEIT: "套餐到期调整",
}

MANUAL_ACTIONS = {
    QuotaLedgerEntry.Action.GRANT,
    QuotaLedgerEntry.Action.COMPENSATE,
    QuotaLedgerEntry.Action.REFUND,
    QuotaLedgerEntry.Action.MANUAL_DEDUCT,
}


def quota_display_name(quota_type):
    return QUOTA_DISPLAY_NAMES.get(quota_type, "额度")


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
    unit_display_name = serializers.SerializerMethodField()

    class Meta:
        model = QuotaAccount
        fields = (
            "id",
            "quota_type",
            "display_name",
            "unit",
            "unit_display_name",
            "scope",
            "entitlement_amount",
            "available",
            "frozen",
            "cycle_started_at",
            "cycle_ends_at",
            "version",
        )

    def get_display_name(self, obj):
        return quota_display_name(obj.quota_type)

    def get_unit_display_name(self, obj):
        return UNIT_DISPLAY_NAMES.get(obj.unit, "份")


class UserQuotaSummarySerializer(serializers.Serializer):
    quota_type = serializers.CharField(max_length=100)
    display_name = serializers.SerializerMethodField()
    unit = serializers.CharField(max_length=50)
    unit_display_name = serializers.SerializerMethodField()
    scope = serializers.CharField(max_length=24)
    entitlement_amount = serializers.IntegerField(min_value=0)
    available = serializers.IntegerField(min_value=0)
    frozen = serializers.IntegerField(min_value=0)
    total_amount = serializers.IntegerField(min_value=0)
    used_amount = serializers.IntegerField(min_value=0)
    remaining_amount = serializers.IntegerField(min_value=0)

    def get_display_name(self, obj):
        return quota_display_name(obj["quota_type"])

    def get_unit_display_name(self, obj):
        return UNIT_DISPLAY_NAMES.get(obj["unit"], "份")


class UserQuotaLedgerSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()
    unit_display_name = serializers.SerializerMethodField()
    action_name = serializers.SerializerMethodField()
    action_label = serializers.SerializerMethodField()
    change_amount = serializers.SerializerMethodField()
    amount = serializers.SerializerMethodField()
    status_label = serializers.SerializerMethodField()
    related_object = serializers.SerializerMethodField()
    remaining_amount = serializers.IntegerField(source="available_after")
    pending_amount = serializers.IntegerField(source="frozen_after")
    description = serializers.SerializerMethodField()
    reason = serializers.SerializerMethodField()

    class Meta:
        model = QuotaLedgerEntry
        fields = (
            "id",
            "quota_type",
            "display_name",
            "unit_display_name",
            "action",
            "action_name",
            "action_label",
            "change_amount",
            "amount",
            "available_before",
            "available_delta",
            "available_after",
            "frozen_before",
            "frozen_delta",
            "frozen_after",
            "remaining_amount",
            "pending_amount",
            "status_label",
            "related_object",
            "description",
            "reason",
            "created_at",
        )

    def get_display_name(self, obj):
        return quota_display_name(obj.quota_type)

    def get_unit_display_name(self, obj):
        return UNIT_DISPLAY_NAMES.get(obj.account.unit, "份")

    def get_action_name(self, obj):
        return LEDGER_ACTION_NAMES.get(obj.action, "额度更新")

    def get_action_label(self, obj):
        return self.get_action_name(obj)

    def get_change_amount(self, obj):
        if obj.action == QuotaLedgerEntry.Action.CONSUME:
            return obj.frozen_delta
        if obj.action == QuotaLedgerEntry.Action.FREEZE:
            return obj.available_delta
        if obj.action == QuotaLedgerEntry.Action.RELEASE:
            return obj.available_delta
        return obj.available_delta

    def get_amount(self, obj):
        return abs(self.get_change_amount(obj))

    def get_status_label(self, obj):
        if obj.action == QuotaLedgerEntry.Action.FREEZE:
            return "处理中"
        if obj.action == QuotaLedgerEntry.Action.RELEASE:
            return "已退回"
        return "已完成"

    def get_related_object(self, obj):
        names = {
            "geo_detection": "GEO 检测",
            "article_generation": "文章生成",
            "image_generation": "图片生成",
            "keyword_generation": "关键词生成",
            "question_bank_generation": "问题库生成",
            "source_index_scan": "信源扫描",
            "negative_index_scan": "负面信息扫描",
            "website_audit": "官网检测",
            "website_generation": "官网生成",
            "video_script_generation": "视频脚本生成",
            "auto_publish": "自动发文",
            "quota_adjustment": "人工额度调整",
        }
        return names.get(obj.business_type, "额度变更")

    def get_description(self, obj):
        return LEDGER_ACTION_NAMES.get(obj.action, "额度已更新")

    def get_reason(self, obj):
        return obj.safe_reason if obj.action in MANUAL_ACTIONS else ""


class AdminQuotaAccountSerializer(UserQuotaAccountSerializer):
    user_id = serializers.UUIDField()
    user_nickname = serializers.CharField(source="user.nickname")
    subscription_id = serializers.UUIDField()
    last_ledger_entry_id = serializers.UUIDField(allow_null=True)
    display_name = serializers.SerializerMethodField()
    unit_display_name = serializers.SerializerMethodField()
    plan_id = serializers.UUIDField(source="subscription.plan_id")
    plan_name = serializers.CharField(source="subscription.plan.name")
    plan_code = serializers.CharField(source="subscription.plan.code")
    plan_version_id = serializers.UUIDField(source="subscription.plan_version_id")
    plan_version_no = serializers.IntegerField(source="subscription.plan_version_no")
    subscription_status = serializers.CharField(source="subscription.status")
    subscription_starts_at = serializers.DateTimeField(source="subscription.starts_at")
    subscription_ends_at = serializers.DateTimeField(source="subscription.ends_at")
    is_trial = serializers.BooleanField(source="subscription.is_trial")
    used_amount = serializers.SerializerMethodField()
    total_amount = serializers.SerializerMethodField()
    remaining_amount = serializers.IntegerField(source="available")
    last_adjustment = serializers.SerializerMethodField()

    class Meta:
        model = QuotaAccount
        fields = (
            "id",
            "user_id",
            "user_nickname",
            "subscription_id",
            "plan_id",
            "plan_name",
            "plan_code",
            "plan_version_id",
            "plan_version_no",
            "subscription_status",
            "subscription_starts_at",
            "subscription_ends_at",
            "is_trial",
            "quota_type",
            "display_name",
            "unit",
            "unit_display_name",
            "scope",
            "entitlement_amount",
            "available",
            "frozen",
            "total_amount",
            "used_amount",
            "remaining_amount",
            "cycle_started_at",
            "cycle_ends_at",
            "ledger_sequence",
            "last_ledger_entry_id",
            "last_adjustment",
            "version",
            "created_at",
            "updated_at",
        )

    def get_used_amount(self, obj):
        return max(-obj.consumed_frozen_delta, 0)

    def get_total_amount(self, obj):
        return obj.available + obj.frozen + self.get_used_amount(obj)

    def get_last_adjustment(self, obj):
        if not obj.last_adjustment_action:
            return None
        return {
            "action": obj.last_adjustment_action,
            "action_name": LEDGER_ACTION_NAMES.get(obj.last_adjustment_action, "额度更新"),
            "reason": obj.last_adjustment_reason or "",
            "operator_name": obj.last_adjustment_actor_nickname or "系统管理员",
            "created_at": obj.last_adjustment_at,
        }


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
    if (
        value not in QUOTA_BY_KEY
        or QUOTA_BY_KEY[value].subject_level
        or not QUOTA_BY_KEY[value].customer_visible
    ):
        raise serializers.ValidationError("\u989d\u5ea6\u7c7b\u578b\u4e0d\u6b63\u786e\u3002")
    return value
