import unicodedata

from rest_framework import serializers


def validate_safe_plain_text(
    value: str,
    *,
    field_label: str,
    max_length: int,
    required: bool,
) -> str:
    normalized = value.strip()
    if required and not normalized:
        raise serializers.ValidationError(f"请输入{field_label}。", code="blank")
    if len(normalized) > max_length:
        raise serializers.ValidationError(
            f"{field_label}不能超过 {max_length} 个字符。",
            code="max_length",
        )
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        raise serializers.ValidationError(f"{field_label}不能包含控制字符。", code="invalid")
    if "<" in normalized or ">" in normalized:
        raise serializers.ValidationError(f"{field_label}不能包含 HTML。", code="invalid")
    return normalized


def validate_nickname(value: str) -> str:
    return validate_safe_plain_text(value, field_label="昵称", max_length=50, required=True)
