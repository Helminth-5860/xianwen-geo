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


def validate_runtime_configuration() -> None:
    configured = set(getattr(settings, "PUBLISHING_ENABLED_PLATFORM_KEYS", ()) or ())
    unknown = configured - _PLATFORM_KEYS
    if unknown:
        raise ImproperlyConfigured(
            "PUBLISHING_ENABLED_PLATFORM_KEYS contains unsupported platform keys."
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

    if not configured:
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

    if os.getenv("APP_ENV", "local").strip().lower() == "production" and not encryption_key:
        # Production platform cookies/tokens must use a dedicated key, not a key derived
        # from Django SECRET_KEY, so credential rotation and application signing stay separate.
        raise ImproperlyConfigured(
            "PUBLISHING_CREDENTIAL_ENCRYPTION_KEY is required when publishing is enabled in production."
        )
