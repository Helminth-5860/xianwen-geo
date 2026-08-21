import re
from collections.abc import Mapping
from typing import Any

REDACTED = "[REDACTED]"
_PUBLIC_SHARE_PATH = re.compile(
    r"(?P<prefix>/public/report-shares/)[^/]+(?P<suffix>(?:/unlock|/pdf)?/?$)"
)

SENSITIVE_FIELD_NAMES = {
    "authorization",
    "cookie",
    "set_cookie",
    "api_key",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "password",
    "password_confirm",
    "sms_code",
}


def normalize_field_name(field_name: object) -> str:
    return str(field_name).strip().lower().replace("-", "_")


def is_sensitive_field(field_name: object) -> bool:
    normalized = normalize_field_name(field_name)
    if normalized in SENSITIVE_FIELD_NAMES:
        return True
    return normalized.endswith(("_api_key", "_secret", "_token", "_password"))


def redact_sensitive_data(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: REDACTED if is_sensitive_field(key) else redact_sensitive_data(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive_data(item) for item in value)
    return value


def redact_request_path(path: object) -> str:
    """Remove one-time report-share tokens before application logging."""

    return _PUBLIC_SHARE_PATH.sub(
        lambda match: f"{match.group('prefix')}{REDACTED}{match.group('suffix')}", str(path)
    )
