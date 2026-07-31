import unicodedata

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import User
from .phone_numbers import mask_phone, normalize_phone
from .sms.purposes import SmsPurpose


class NormalizedPhoneSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=32, trim_whitespace=True)

    def validate_phone(self, value: str) -> str:
        try:
            return normalize_phone(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message, code=exc.code) from exc


class SmsSendSerializer(NormalizedPhoneSerializer):
    purpose = serializers.ChoiceField(choices=[purpose.value for purpose in SmsPurpose])


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
        nickname = value.strip()
        if not nickname:
            raise serializers.ValidationError("请输入昵称。", code="blank")
        if any(unicodedata.category(character).startswith("C") for character in nickname):
            raise serializers.ValidationError("昵称不能包含控制字符。", code="invalid")
        return nickname

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

    class Meta:
        model = User
        fields = (
            "id",
            "nickname",
            "phone_masked",
            "approval_status",
            "account_status",
        )

    def get_phone_masked(self, user: User) -> str:
        return mask_phone(user.phone)
