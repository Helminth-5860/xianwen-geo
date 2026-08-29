from django.conf import settings
from django.core.cache import cache

from apps.users.sms.security import client_ip_address
from apps.web_sources.exceptions import WebSourceRateLimited, WebSourceUnavailable
from apps.web_sources.url_security import fingerprint


def _increment(key: str, limit: int, ttl: int) -> None:
    try:
        if cache.add(key, 1, timeout=ttl):
            value = 1
        else:
            value = cache.incr(key)
    except Exception as exc:
        raise WebSourceUnavailable from exc
    if value > limit:
        raise WebSourceRateLimited


def enforce_publication_verification_limits(*, request, user_id, subject_id, host: str) -> None:
    ip = client_ip_address(request)
    window = settings.WEB_IMPORT_RATE_LIMIT_WINDOW_SECONDS
    dimensions = (
        ("user", str(user_id), settings.WEB_IMPORT_RATE_LIMIT_USER),
        ("ip", ip, settings.WEB_IMPORT_RATE_LIMIT_IP),
        ("subject", str(subject_id), settings.WEB_IMPORT_RATE_LIMIT_SUBJECT),
        ("host", host, settings.WEB_IMPORT_RATE_LIMIT_HOST),
    )
    for label, raw, limit in dimensions:
        _increment(
            f"publication-verify:v1:limit:{label}:{fingerprint(label, raw)}",
            limit,
            window,
        )
