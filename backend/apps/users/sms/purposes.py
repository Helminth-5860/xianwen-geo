from enum import StrEnum


class SmsPurpose(StrEnum):
    REGISTER = "register"
    LOGIN = "login"
    PASSWORD_RESET = "password_reset"


def parse_sms_purpose(value: object) -> SmsPurpose:
    if not isinstance(value, str):
        raise ValueError("不支持的验证码用途。")
    try:
        return SmsPurpose(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("不支持的验证码用途。") from exc
