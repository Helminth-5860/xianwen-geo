import hashlib
import hmac
import json

from django.conf import settings

from .enrichment_exceptions import SubjectEnrichmentIdempotencyRequired


def canonical_digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def derive_idempotency(*, user_id, subject_id, raw_key: str) -> str:
    if not isinstance(raw_key, str) or not 16 <= len(raw_key.encode()) <= 128:
        raise SubjectEnrichmentIdempotencyRequired
    master = settings.SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY.encode()
    subkey = hmac.new(master, b"subject-enrichment:idempotency:v1", hashlib.sha256).digest()
    scope = f"user={user_id}|subject={subject_id}|key={raw_key}"
    return hmac.new(subkey, scope.encode(), hashlib.sha256).hexdigest()
