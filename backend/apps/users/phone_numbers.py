import re
from hashlib import sha256
from hmac import new as hmac_new

from django.conf import settings
from django.core.exceptions import ValidationError

MAINLAND_PHONE_PATTERN = re.compile(r"^1[3-9]\d{9}$")
PHONE_SEPARATORS = re.compile(r"[\s-]+")


def normalize_phone(value: object) -> str:
    if not isinstance(value, str):
        raise ValidationError("请输入有效的中国大陆手机号。", code="invalid_phone")

    compact = PHONE_SEPARATORS.sub("", value.strip())
    if compact.startswith("+86"):
        national_number = compact[3:]
    elif compact.startswith("0086"):
        national_number = compact[4:]
    else:
        national_number = compact

    if not MAINLAND_PHONE_PATTERN.fullmatch(national_number):
        raise ValidationError("请输入有效的中国大陆手机号。", code="invalid_phone")
    return f"+86{national_number}"


def phone_fingerprint(normalized_phone: str) -> str:
    return hmac_fingerprint("phone", normalized_phone)


def hmac_fingerprint(namespace: str, value: str) -> str:
    key = settings.SECRET_KEY.encode("utf-8")
    message = f"{namespace}:{value}".encode()
    return hmac_new(key, message, sha256).hexdigest()


def mask_phone(normalized_phone: str) -> str:
    national_number = normalized_phone.removeprefix("+86")
    return f"+86 {national_number[:3]}****{national_number[-4:]}"
