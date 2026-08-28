from __future__ import annotations

from django.core.cache import cache
from django.utils import timezone


_FAILURE_WINDOW_SECONDS = 20 * 60
_OPEN_SECONDS = 30 * 60
_THRESHOLD = 5


def _failure_key(platform_key: str) -> str:
    return f"publishing:platform-health:{platform_key}:failures"


def _open_key(platform_key: str) -> str:
    return f"publishing:platform-health:{platform_key}:open"


def _error_key(platform_key: str) -> str:
    return f"publishing:platform-health:{platform_key}:error"


def platform_circuit_open(platform_key: str) -> bool:
    return bool(cache.get(_open_key(platform_key)))


def record_platform_success(platform_key: str) -> None:
    cache.delete_many((_failure_key(platform_key), _open_key(platform_key), _error_key(platform_key)))
    cache.set(
        f"publishing:platform-health:{platform_key}:success-at",
        timezone.now().isoformat(),
        timeout=7 * 24 * 60 * 60,
    )


def record_platform_failure(platform_key: str, error_code: str) -> None:
    key = _failure_key(platform_key)
    if cache.add(key, 1, timeout=_FAILURE_WINDOW_SECONDS):
        count = 1
    else:
        try:
            count = int(cache.incr(key))
        except (ValueError, TypeError):
            cache.set(key, 1, timeout=_FAILURE_WINDOW_SECONDS)
            count = 1
    cache.set(_error_key(platform_key), error_code[:100], timeout=_FAILURE_WINDOW_SECONDS)
    if count >= _THRESHOLD:
        cache.set(_open_key(platform_key), "1", timeout=_OPEN_SECONDS)


def platform_health_payload(platform_key: str) -> dict[str, object]:
    open_state = platform_circuit_open(platform_key)
    try:
        failures = int(cache.get(_failure_key(platform_key)) or 0)
    except (TypeError, ValueError):
        failures = 0
    return {
        "status": "paused" if open_state else ("degraded" if failures else "healthy"),
        "recent_failures": failures,
    }
