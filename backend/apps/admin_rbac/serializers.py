from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.users.models import User
from apps.users.phone_numbers import mask_phone, normalize_phone
from apps.users.validators import validate_nickname, validate_safe_plain_text

from .models import (
    AdminPermission,
    AdminProfile,
    AdminRole,
    CustomerAssignment,
    RoleIpAllowlistEntry,
    SuperuserIpAllowlistEntry,
    SuperuserSecurityPolicy,
)
from .security import normalize_network


class RoleSerializer(serializers.ModelSerializer):
    permission_keys = serializers.SerializerMethodField()

    class Meta:
        model = AdminRole
        fields = (
            "id",
            "name",
            "description",
            "status",
            "data_scope",
            "version",
            "require_sms_2fa",
            "ip_allowlist_enabled",
            "security_version",
            "permission_keys",
            "created_at",
            "updated_at",
        )

    def get_permission_keys(self, role):
        return list(
            role.permission_links.select_related("permission")
            .order_by("permission__sort_order")
            .values_list("permission__key", flat=True)
        )


class RoleCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80, trim_whitespace=False)
    description = serializers.CharField(
        max_length=500, required=False, allow_blank=True, trim_whitespace=False
    )
    data_scope = serializers.ChoiceField(choices=AdminRole.DataScope.values)


class RoleUpdateSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    name = serializers.CharField(max_length=80, required=False, trim_whitespace=False)
    description = serializers.CharField(
        max_length=500, required=False, allow_blank=True, trim_whitespace=False
    )
    data_scope = serializers.ChoiceField(choices=AdminRole.DataScope.values, required=False)
    permission_keys = serializers.ListField(
        child=serializers.CharField(max_length=100), required=False, allow_empty=True
    )


class VersionSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdminPermission
        fields = (
            "key",
            "name",
            "module",
            "permission_type",
            "description",
            "status",
            "sort_order",
            "superuser_only",
        )


class AdminProfileSerializer(serializers.ModelSerializer):
    nickname = serializers.CharField(source="user.nickname")
    phone_masked = serializers.SerializerMethodField()
    is_superuser = serializers.BooleanField(source="user.is_superuser")
    role = RoleSerializer()

    class Meta:
        model = AdminProfile
        fields = (
            "id",
            "nickname",
            "phone_masked",
            "is_superuser",
            "admin_status",
            "version",
            "role",
            "created_at",
            "updated_at",
        )

    def get_phone_masked(self, profile):
        return mask_phone(profile.user.phone)


class AdminCreateSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=32)
    nickname = serializers.CharField(max_length=50, trim_whitespace=False)
    password = serializers.CharField(max_length=128, write_only=True, trim_whitespace=False)
    role_id = serializers.UUIDField()

    def validate_phone(self, value):
        return normalize_phone(value)

    def validate_nickname(self, value):
        return validate_nickname(value)

    def validate(self, attrs):
        provisional = User(phone=attrs["phone"], nickname=attrs["nickname"])
        try:
            validate_password(attrs["password"], provisional)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": exc.messages}) from exc
        return attrs


class AdminUpdateSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    nickname = serializers.CharField(max_length=50, required=False, trim_whitespace=False)
    role_id = serializers.UUIDField(required=False)

    def validate_nickname(self, value):
        return validate_nickname(value)


class AssignmentSerializer(serializers.ModelSerializer):
    owner_admin_id = serializers.UUIDField(allow_null=True)

    class Meta:
        model = CustomerAssignment
        fields = ("id", "customer_id", "owner_admin_id", "version", "assigned_at")


class AssignmentUpdateSerializer(serializers.Serializer):
    owner_admin_id = serializers.UUIDField(allow_null=True)
    expected_version = serializers.IntegerField(min_value=0)
    reason = serializers.CharField(
        max_length=200, required=False, allow_blank=True, trim_whitespace=False
    )

    def validate_reason(self, value):
        return validate_safe_plain_text(
            value, field_label="归属变更原因", max_length=200, required=False
        )


class AdminPasswordLoginSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=32, trim_whitespace=True)
    password = serializers.CharField(max_length=128, write_only=True, trim_whitespace=False)

    def validate_phone(self, value):
        return normalize_phone(value)


class AdminChallengeSerializer(serializers.Serializer):
    challenge_id = serializers.CharField(max_length=128, write_only=True, trim_whitespace=False)


class AdminChallengeVerifySerializer(AdminChallengeSerializer):
    sms_code = serializers.RegexField(
        regex=r"^\d{6}$", max_length=6, write_only=True, trim_whitespace=False
    )


class SecurityMutationSerializer(serializers.Serializer):
    current_password = serializers.CharField(max_length=128, write_only=True, trim_whitespace=False)
    expected_security_version = serializers.IntegerField(min_value=1)
    confirm_lockout = serializers.BooleanField(default=False, required=False)


class RoleSecurityUpdateSerializer(SecurityMutationSerializer):
    require_sms_2fa = serializers.BooleanField(required=False)
    ip_allowlist_enabled = serializers.BooleanField(required=False)


class SuperuserSecurityUpdateSerializer(SecurityMutationSerializer):
    ip_allowlist_enabled = serializers.BooleanField(required=False)


class IpAllowlistCreateSerializer(SecurityMutationSerializer):
    network_cidr = serializers.CharField(max_length=64, trim_whitespace=False)
    label = serializers.CharField(  # type: ignore[assignment]
        max_length=100, required=False, allow_blank=True, default=""
    )

    def validate_network_cidr(self, value):
        try:
            return normalize_network(value)[0]
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc


class IpAllowlistUpdateSerializer(SecurityMutationSerializer):
    status = serializers.ChoiceField(choices=("active", "inactive"))
    label = serializers.CharField(  # type: ignore[assignment]
        max_length=100, required=False, allow_blank=True
    )


class RoleIpAllowlistSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoleIpAllowlistEntry
        fields = ("id", "network_cidr", "ip_version", "label", "status", "created_at", "updated_at")


class SuperuserIpAllowlistSerializer(serializers.ModelSerializer):
    class Meta:
        model = SuperuserIpAllowlistEntry
        fields = ("id", "network_cidr", "ip_version", "label", "status", "created_at", "updated_at")


class SuperuserSecurityPolicySerializer(serializers.ModelSerializer):
    require_sms_2fa = serializers.SerializerMethodField()

    class Meta:
        model = SuperuserSecurityPolicy
        fields = ("id", "ip_allowlist_enabled", "security_version", "require_sms_2fa")

    def get_require_sms_2fa(self, policy):
        return True
