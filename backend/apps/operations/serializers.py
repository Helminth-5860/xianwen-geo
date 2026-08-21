from rest_framework import serializers

from .models import Announcement, CustomerContactLog


class BoundedPageSerializer(serializers.Serializer):
    page = serializers.IntegerField(required=False, min_value=1, max_value=100_000, default=1)
    page_size = serializers.IntegerField(required=False, min_value=1, max_value=100, default=20)


class CustomerProfileUpdateSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    status_id = serializers.UUIDField(required=False, allow_null=True)
    source = serializers.CharField(  # type: ignore[assignment]
        required=False, allow_blank=True, max_length=100, trim_whitespace=True
    )
    internal_note = serializers.CharField(
        required=False, allow_blank=True, max_length=2000, trim_whitespace=True
    )
    tag_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True, max_length=50
    )

    def validate_tag_ids(self, values):
        if len(values) != len(set(values)):
            raise serializers.ValidationError("标签不能重复。")
        return values


class ContactCreateSerializer(serializers.Serializer):
    contacted_at = serializers.DateTimeField()
    method = serializers.ChoiceField(choices=CustomerContactLog.Method.choices)
    content = serializers.CharField(max_length=4000, trim_whitespace=True)
    next_followup_at = serializers.DateTimeField(required=False, allow_null=True)
    followup_note = serializers.CharField(
        required=False, allow_blank=True, max_length=2000, trim_whitespace=True
    )

    def validate(self, attrs):
        next_at = attrs.get("next_followup_at")
        if next_at is not None and next_at <= attrs["contacted_at"]:
            raise serializers.ValidationError(
                {"next_followup_at": "下次跟进时间必须晚于联系时间。"}
            )
        return attrs


class FollowupCreateSerializer(serializers.Serializer):
    due_at = serializers.DateTimeField()
    note = serializers.CharField(max_length=2000, trim_whitespace=True)


class FollowupActionSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    action = serializers.ChoiceField(choices=("complete", "cancel", "postpone"))
    due_at = serializers.DateTimeField(required=False)
    note = serializers.CharField(required=False, allow_blank=True, max_length=2000)

    def validate(self, attrs):
        if attrs["action"] == "postpone" and "due_at" not in attrs:
            raise serializers.ValidationError({"due_at": "延期必须提供新的到期时间。"})
        return attrs


class AnnouncementWriteSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(required=False, min_value=1)
    title = serializers.CharField(required=False, max_length=200, trim_whitespace=True)
    body = serializers.CharField(required=False, max_length=20_000, trim_whitespace=True)
    audience = serializers.ChoiceField(
        required=False, choices=Announcement.Audience.choices, default=Announcement.Audience.ALL
    )
    audience_keys = serializers.ListField(
        child=serializers.CharField(max_length=100), required=False, max_length=500, default=list
    )
    starts_at = serializers.DateTimeField(required=False, allow_null=True)
    ends_at = serializers.DateTimeField(required=False, allow_null=True)
    pinned = serializers.BooleanField(required=False, default=False)

    def validate_audience_keys(self, values):
        normalized = [value.strip() for value in values if value.strip()]
        if len(normalized) != len(set(normalized)):
            raise serializers.ValidationError("公告目标不能重复。")
        return normalized

    def validate(self, attrs):
        audience = attrs.get("audience", Announcement.Audience.ALL)
        keys = attrs.get("audience_keys", [])
        if audience == Announcement.Audience.ALL and keys:
            raise serializers.ValidationError({"audience_keys": "全体公告不能设置目标列表。"})
        if audience != Announcement.Audience.ALL and not keys:
            raise serializers.ValidationError({"audience_keys": "定向公告必须设置目标列表。"})
        starts_at = attrs.get("starts_at")
        ends_at = attrs.get("ends_at")
        if starts_at and ends_at and ends_at <= starts_at:
            raise serializers.ValidationError({"ends_at": "结束时间必须晚于开始时间。"})
        return attrs


class AnnouncementActionSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    action = serializers.ChoiceField(choices=("publish", "disable"))


class FeedbackCreateSerializer(serializers.Serializer):
    subject_id = serializers.UUIDField(required=False, allow_null=True)
    module = serializers.RegexField(regex=r"^[a-z][a-z0-9_.-]{1,63}$", max_length=64)
    description = serializers.CharField(min_length=2, max_length=10_000, trim_whitespace=True)


class FeedbackReplySerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    action = serializers.ChoiceField(choices=("reply", "close"))
    reply = serializers.CharField(required=False, allow_blank=True, max_length=10_000)

    def validate(self, attrs):
        if attrs["action"] == "reply" and not attrs.get("reply", "").strip():
            raise serializers.ValidationError({"reply": "回复内容不能为空。"})
        return attrs


class SupportViewCreateSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=4, max_length=1000, trim_whitespace=True)
    forced = serializers.BooleanField(default=False)


class SupportViewDecisionSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    decision = serializers.ChoiceField(choices=("authorize", "reject", "revoke"))


class ModerationDecisionSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    decision = serializers.ChoiceField(choices=("approve", "reject"))
    responsibility = serializers.ChoiceField(choices=("system", "user"))
    reason_code = serializers.RegexField(regex=r"^[A-Z][A-Z0-9_]{2,99}$", max_length=100)
    note = serializers.CharField(required=False, allow_blank=True, max_length=1000)


class CustomerExportSerializer(serializers.Serializer):
    format = serializers.ChoiceField(choices=("csv",))
    confirmation = serializers.ChoiceField(choices=("EXPORT_SCOPED_CUSTOMERS",))


class CustomerCatalogUpdateSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    name = serializers.CharField(required=False, min_length=1, max_length=100)
    state = serializers.ChoiceField(required=False, choices=("active", "inactive"))

    def validate(self, attrs):
        if len(attrs) == 1:
            raise serializers.ValidationError("必须提供 name 或 state。")
        return attrs


class SystemAlertActionSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    action = serializers.ChoiceField(choices=("acknowledge", "resolve"))
