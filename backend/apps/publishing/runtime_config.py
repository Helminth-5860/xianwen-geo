from __future__ import annotations

import os

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

_PLATFORM_KEYS = {
    "wechat",
    "toutiao",
    "baijiahao",
    "zhihu",
    "xiaohongshu",
    "weibo",
    "bilibili",
    "douyin",
    "qq",
    "sohu",
    "csdn",
    "juejin",
    "cnblogs",
    "oschina",
    "segmentfault",
    "jianshu",
    "douban",
}
_BROWSER_PLATFORM_KEYS = _PLATFORM_KEYS - {"wechat"}


def _worker_experimental_keys() -> set[str]:
    return {
        item.strip().lower()
        for item in os.getenv("PUBLISHING_WORKER_EXPERIMENTAL_PLATFORM_KEYS", "").split(",")
        if item.strip()
    }


def _validation_platform_keys() -> set[str]:
    return {
        item.strip().lower()
        for item in os.getenv("PUBLISHING_VALIDATION_PLATFORM_KEYS", "").split(",")
        if item.strip()
    }


def validate_runtime_configuration() -> None:
    configured = set(getattr(settings, "PUBLISHING_ENABLED_PLATFORM_KEYS", ()) or ())
    validation = _validation_platform_keys()
    unknown = configured - _PLATFORM_KEYS
    if unknown:
        raise ImproperlyConfigured(
            "PUBLISHING_ENABLED_PLATFORM_KEYS contains unsupported platform keys."
        )
    unknown_validation = validation - _PLATFORM_KEYS
    if unknown_validation:
        raise ImproperlyConfigured(
            "PUBLISHING_VALIDATION_PLATFORM_KEYS contains unsupported platform keys."
        )

    encryption_key = str(
        getattr(settings, "PUBLISHING_CREDENTIAL_ENCRYPTION_KEY", "") or ""
    ).strip()
    if encryption_key:
        try:
            Fernet(encryption_key.encode("ascii"))
        except (ValueError, TypeError, UnicodeEncodeError) as exc:
            raise ImproperlyConfigured(
                "PUBLISHING_CREDENTIAL_ENCRYPTION_KEY must be a valid Fernet key."
            ) from exc

    if not configured and not validation:
        return

    worker_base_url = str(getattr(settings, "PUBLISHING_WORKER_BASE_URL", "") or "").strip()
    worker_secret = str(
        getattr(settings, "PUBLISHING_WORKER_INTERNAL_SECRET", "") or ""
    ).strip()
    if not worker_base_url:
        raise ImproperlyConfigured(
            "PUBLISHING_WORKER_BASE_URL is required before enabling publishing platforms."
        )
    if len(worker_secret) < 32:
        raise ImproperlyConfigured(
            "PUBLISHING_WORKER_INTERNAL_SECRET is required before enabling publishing platforms."
        )

    # Both public rollout and internal acceptance exercise the same browser
    # automation worker. Requiring the worker-side gate for both prevents a
    # validation-only platform from being exposed by a Django-only setting.
    browser_enabled = (configured | validation) & _BROWSER_PLATFORM_KEYS
    worker_enabled = _worker_experimental_keys()
    missing_worker_gate = browser_enabled - worker_enabled
    if missing_worker_gate:
        raise ImproperlyConfigured(
            "Browser publishing platforms enabled in Django must also be explicitly enabled "
            "in PUBLISHING_WORKER_EXPERIMENTAL_PLATFORM_KEYS after real-account acceptance."
        )
    unknown_worker_keys = worker_enabled - _BROWSER_PLATFORM_KEYS
    if unknown_worker_keys:
        raise ImproperlyConfigured(
            "PUBLISHING_WORKER_EXPERIMENTAL_PLATFORM_KEYS contains unsupported browser platform keys."
        )

    if os.getenv("APP_ENV", "local").strip().lower() == "production" and not encryption_key:
        # Production platform cookies/tokens must use a dedicated key, not a key derived
        # from Django SECRET_KEY, so credential rotation and application signing stay separate.
        raise ImproperlyConfigured(
            "PUBLISHING_CREDENTIAL_ENCRYPTION_KEY is required when publishing is enabled in production."
        )
