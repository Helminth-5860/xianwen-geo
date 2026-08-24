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


class RegistrationReferenceSerializer(serializers.Serializer):
    ref = serializers.CharField(max_length=512, trim_whitespace=False)

    def validate_ref(self, value):
        from apps.admin_rbac.registration_links import (
            InvalidRegistrationReference,
            resolve_registration_admin,
        )

        try:
            resolve_registration_admin(value)
        except InvalidRegistrationReference as exc:
            raise serializers.ValidationError("注册链接无效、已过期或所属代理不可用。") from exc
        return value


class RegistrationSerializer(SmsCodeSerializer):
    ref = serializers.CharField(
        max_length=512,
        trim_whitespace=False,
        required=False,
        allow_blank=True,
        default="",
    )
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
        unknown_fields = set(self.initial_data) - set(self.fields)
        if unknown_fields:
            raise serializers.ValidationError(
                {field: ["不支持该注册字段。"] for field in sorted(unknown_fields)}
            )
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
    commercial_identity = serializers.SerializerMethodField()
    home_route = serializers.SerializerMethodField()
    tenant = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "nickname",
            "phone_masked",
            "account_status",
            "commercial_identity",
            "home_route",
            "tenant",
        )

    def get_phone_masked(self, user: User) -> str:
        return mask_phone(user.phone)

    def get_commercial_identity(self, user: User) -> str:
        return commercial_identity(user).value

    def get_home_route(self, user: User) -> str:
        return commercial_home_route(user)

    def get_tenant(self, user: User) -> dict[str, str] | None:
        tenant = user.tenant if user.tenant_id else None
        return tenant_branding(tenant)


class PaginationSerializer(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=20)


class AdminUserListQuerySerializer(NormalizedPhoneSerializer):
    phone = serializers.CharField(max_length=32, required=False, trim_whitespace=True)
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
            "account_status",
            "is_test_account",
            "status_version",
            "created_at",
        )

    def get_phone_masked(self, user: User) -> str:
        return mask_phone(user.phone)


class AdminUserDetailSerializer(AdminUserListSerializer):
    pass


class TestAccountActionSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    confirmed = serializers.BooleanField()
    current_password = serializers.CharField(
        max_length=128,
        write_only=True,
        trim_whitespace=False,
    )


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
