from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .commercial import commercial_home_route, commercial_identity, tenant_branding
from .models import Notification, User, UserStatusEvent
from .phone_numbers import mask_phone, normalize_phone
from .sms.purposes import PUBLIC_SMS_PURPOSES
from .validators import validate_nickname, validate_safe_plain_text


class NormalizedPhoneSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=32, trim_whitespace=True)

    def validate_phone(self, value: str) -> str:
        try:
            return normalize_phone(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message, code=exc.code) from exc


class SmsSendSerializer(NormalizedPhoneSerializer):
    purpose = serializers.ChoiceField(choices=[purpose.value for purpose in PUBLIC_SMS_PURPOSES])


class PasswordLoginSerializer(NormalizedPhoneSerializer):
    password = serializers.CharField(
        max_length=128,
        trim_whitespace=False,
        write_only=True,
        style={"input_type": "password"},
    )


class SmsCodeSerializer(NormalizedPhoneSerializer):
    sms_code = serializers.CharField(
        max_length=32,
        trim_whitespace=False,
        write_only=True,
        style={"input_type": "password"},
    )


class RegistrationSerializer(SmsCodeSerializer):
    nickname = serializers.CharField(max_length=50, trim_whitespace=True)
    password = serializers.CharField(
        max_length=128,
        trim_whitespace=False,
        write_only=True,
        style={"input_type": "password"},
    )

    def validate_nickname(self, value: str) -> str:
        return validate_nickname(value)

    def validate(self, attrs):
        provisional_user = User(phone=attrs["phone"], nickname=attrs["nickname"])
        try:
            validate_password(attrs["password"], provisional_user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": exc.messages}) from exc
        return attrs


class SmsLoginSerializer(SmsCodeSerializer):
    pass


class PasswordResetSerializer(SmsCodeSerializer):
    new_password = serializers.CharField(
        max_length=128,
        trim_whitespace=False,
        write_only=True,
        style={"input_type": "password"},
    )

    def validate(self, attrs):
        provisional_user = User(phone=attrs["phone"], nickname="")
        try:
            validate_password(attrs["new_password"], provisional_user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": exc.messages}) from exc
        return attrs


class CurrentUserSerializer(serializers.ModelSerializer):
    phone_masked = serializers.SerializerMethodField()
    approval_reason = serializers.SerializerMethodField()
    commercial_identity = serializers.SerializerMethodField()
    home_route = serializers.SerializerMethodField()
    tenant = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "nickname",
            "phone_masked",
            "approval_status",
            "account_status",
            "approval_reason",
            "commercial_identity",
            "home_route",
            "tenant",
        )

    def get_phone_masked(self, user: User) -> str:
        return mask_phone(user.phone)

    def get_approval_reason(self, user: User) -> str | None:
        if user.approval_status == User.ApprovalStatus.REJECTED:
            return user.approval_reason
        return None

    def get_commercial_identity(self, user: User) -> str:
        return commercial_identity(user).value

    def get_home_route(self, user: User) -> str:
        return commercial_home_route(user)

    def get_tenant(self, user: User) -> dict[str, str] | None:
        tenant = user.tenant if user.tenant_id else None
        return tenant_branding(tenant)

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        if representation["approval_reason"] is None:
            representation.pop("approval_reason")
        return representation


class ApprovalResubmitSerializer(serializers.Serializer):
    nickname = serializers.CharField(max_length=50, required=False, trim_whitespace=False)

    def validate(self, attrs):
        unexpected_fields = set(self.initial_data) - {"nickname"}
        if unexpected_fields:
            raise serializers.ValidationError(
                {"non_field_errors": ["重新提交不能修改手机号或其他账号字段。"]}
            )
        return attrs

    def validate_nickname(self, value: str) -> str:
        return validate_nickname(value)


class PaginationSerializer(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=20)


class AdminUserListQuerySerializer(NormalizedPhoneSerializer):
    phone = serializers.CharField(max_length=32, required=False, trim_whitespace=True)
    approval_status = serializers.ChoiceField(
        choices=User.ApprovalStatus.values,
        required=False,
    )
    account_status = serializers.ChoiceField(
        choices=User.AccountStatus.values,
        required=False,
    )
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=20)


class AdminUserListSerializer(serializers.ModelSerializer):
    phone_masked = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "nickname",
            "phone_masked",
            "approval_status",
            "account_status",
            "status_version",
            "approved_at",
            "created_at",
        )

    def get_phone_masked(self, user: User) -> str:
        return mask_phone(user.phone)


class AdminUserDetailSerializer(AdminUserListSerializer):
    approval_reason = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "nickname",
            "phone_masked",
            "approval_status",
            "account_status",
            "status_version",
            "approved_at",
            "created_at",
            "approval_reason",
        )

    def get_approval_reason(self, user: User) -> str | None:
        if user.approval_status == User.ApprovalStatus.REJECTED:
            return user.approval_reason
        return None


class UserStatusEventSerializer(serializers.ModelSerializer):
    actor_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = UserStatusEvent
        fields = (
            "id",
            "status_domain",
            "event_type",
            "from_value",
            "to_value",
            "reason",
            "actor_id",
            "request_id",
            "created_at",
        )


class ReviewUserSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=("approve", "reject"))
    reason = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
        trim_whitespace=False,
    )
    expected_version = serializers.IntegerField(min_value=1, required=False)
    confirmed = serializers.BooleanField(required=False, default=False)
    current_password = serializers.CharField(
        max_length=128, write_only=True, required=False, default=""
    )

    def validate(self, attrs):
        decision = attrs["decision"]
        if decision == "reject" and "expected_version" not in attrs:
            raise serializers.ValidationError({"expected_version": ["拒绝审核时必须提供。"]})
        reason = attrs.get("reason", "")
        if decision == "reject" and not reason.strip():
            attrs["reason_required"] = True
            return attrs
        attrs["reason"] = validate_safe_plain_text(
            reason,
            field_label="拒绝原因",
            max_length=500,
            required=decision == "reject",
        )
        return attrs


class AccountStatusActionSerializer(serializers.Serializer):
    reason = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
        trim_whitespace=False,
    )
    expected_version = serializers.IntegerField(min_value=1, required=False)
    confirmed = serializers.BooleanField(required=False, default=False)
    current_password = serializers.CharField(
        max_length=128, write_only=True, required=False, default=""
    )

    def validate_reason(self, value: str) -> str:
        return validate_safe_plain_text(
            value,
            field_label="操作原因",
            max_length=500,
            required=False,
        )


class FreezeStatusActionSerializer(AccountStatusActionSerializer):
    expected_version = serializers.IntegerField(min_value=1)


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = (
            "id",
            "notification_type",
            "related_plan_application_id",
            "title",
            "related_subscription_id",
            "safe_summary",
            "read_at",
            "created_at",
        )
