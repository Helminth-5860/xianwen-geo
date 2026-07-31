from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import User
from .phone_numbers import mask_phone, normalize_phone


class PasswordLoginSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=32, trim_whitespace=True)
    password = serializers.CharField(
        max_length=128,
        trim_whitespace=False,
        write_only=True,
        style={"input_type": "password"},
    )

    def validate_phone(self, value: str) -> str:
        try:
            return normalize_phone(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message, code=exc.code) from exc


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
