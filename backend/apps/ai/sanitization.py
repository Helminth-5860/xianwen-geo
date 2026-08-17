from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit, urlunsplit

REDACTED = "[REDACTED]"
TRUNCATED = "[TRUNCATED]"
UNSUPPORTED = "[UNSUPPORTED]"

SENSITIVE_EXACT_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "body",
        "content",
        "cookie",
        "credentials",
        "developer_prompt",
        "detail",
        "diagnostic",
        "diagnostics",
        "error",
        "error_message",
        "input",
        "message",
        "messages",
        "output",
        "password",
        "prompt",
        "raw_body",
        "raw_payload",
        "raw_response",
        "secret",
        "set_cookie",
        "signed_url",
        "source_text",
        "system_prompt",
        "text",
        "token",
        "user_input",
        "user_prompt",
    }
)
SENSITIVE_SUFFIXES = (
    "_api_key",
    "_authorization",
    "_body",
    "_content",
    "_cookie",
    "_credential",
    "_credentials",
    "_input",
    "_message",
    "_messages",
    "_output",
    "_password",
    "_prompt",
    "_secret",
    "_signed_url",
    "_token",
)
SAFE_METRIC_KEYS = frozenset(
    {
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "latency_ms",
        "item_count",
        "source_count",
        "request_count",
        "image_count",
        "mock",
    }
)


def _normalized_key(value: object) -> str:
    return str(value).strip().lower().replace("-", "_")


def _sensitive_key(value: object) -> bool:
    key = _normalized_key(value)
    return key in SENSITIVE_EXACT_KEYS or key.endswith(SENSITIVE_SUFFIXES)


def _bounded_key(value: object) -> str:
    key = str(value).replace("\r", " ").replace("\n", " ")
    return key if len(key) <= 64 else f"{key[:64]}{TRUNCATED}"


def _sanitize_string(value: str, max_string_length: int) -> str:
    parsed = urlsplit(value)
    if parsed.scheme.lower() in {"http", "https"} and parsed.netloc:
        netloc = parsed.netloc
        if parsed.username is not None or parsed.password is not None:
            hostname = parsed.hostname or ""
            if ":" in hostname:
                hostname = f"[{hostname}]"
            netloc = f"{hostname}:{parsed.port}" if parsed.port is not None else hostname
        value = urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
    if len(value) > max_string_length:
        return f"{value[:max_string_length]}{TRUNCATED}"
    return value


def sanitize_provider_payload(
    value: Any,
    *,
    max_depth: int = 5,
    max_items: int = 50,
    max_string_length: int = 256,
    _depth: int = 0,
) -> Any:
    """Return bounded metadata safe for business code, logs, or persistence."""

    if _depth >= max_depth:
        return TRUNCATED
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _sanitize_string(value, max_string_length)
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= max_items:
                sanitized[TRUNCATED] = TRUNCATED
                break
            safe_key = _bounded_key(key)
            sanitized[safe_key] = (
                REDACTED
                if _sensitive_key(key)
                else sanitize_provider_payload(
                    item,
                    max_depth=max_depth,
                    max_items=max_items,
                    max_string_length=max_string_length,
                    _depth=_depth + 1,
                )
            )
        return sanitized
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        items = [
            sanitize_provider_payload(
                item,
                max_depth=max_depth,
                max_items=max_items,
                max_string_length=max_string_length,
                _depth=_depth + 1,
            )
            for item in value[:max_items]
        ]
        if len(value) > max_items:
            items.append(TRUNCATED)
        return items
    return UNSUPPORTED


def sanitize_provider_metrics(metrics: object) -> dict[str, bool | int]:
    if not isinstance(metrics, Mapping):
        return {}
    result: dict[str, bool | int] = {}
    for key, value in metrics.items():
        if key not in SAFE_METRIC_KEYS:
            continue
        if isinstance(value, bool) or (type(value) is int and 0 <= value <= 2**63 - 1):
            result[str(key)] = value
    return result
