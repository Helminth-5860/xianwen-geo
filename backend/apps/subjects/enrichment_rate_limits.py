import hashlib
import hmac

from django.conf import settings
from django.core.cache import cache

from apps.users.sms.security import client_ip_address

from .enrichment_exceptions import (
    SubjectEnrichmentRateLimited,
    SubjectEnrichmentTemporarilyUnavailable,
)


def _fingerprint(label: str, value: str) -> str:
    master = settings.SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY.encode()
    subkey = hmac.new(master, b"subject-enrichment:rate-limit:v1", hashlib.sha256).digest()
    return hmac.new(subkey, f"{label}:{value}".encode(), hashlib.sha256).hexdigest()


def _increment(key: str, limit: int, ttl: int) -> None:
    try:
        if cache.add(key, 1, timeout=ttl):
            value = 1
        else:
            value = cache.incr(key)
    except Exception as exc:
        raise SubjectEnrichmentTemporarilyUnavailable from exc
    if value > limit:
        raise SubjectEnrichmentRateLimited


def enforce_enrichment_limits(*, request, user_id, subject_id) -> None:
    ip = client_ip_address(request)
    window = settings.SUBJECT_ENRICHMENT_RATE_LIMIT_WINDOW_SECONDS
    dimensions = (
        ("user", str(user_id), settings.SUBJECT_ENRICHMENT_RATE_LIMIT_USER),
        ("ip", ip, settings.SUBJECT_ENRICHMENT_RATE_LIMIT_IP),
        ("subject", str(subject_id), settings.SUBJECT_ENRICHMENT_RATE_LIMIT_SUBJECT),
    )
    for label, raw, limit in dimensions:
        _increment(
            f"subject-enrichment:v1:limit:{label}:{_fingerprint(label, raw)}",
            limit,
            window,
        )
