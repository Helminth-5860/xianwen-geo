import hashlib
import hmac
import json

from django.conf import settings

from .generation_exceptions import KeywordGenerationIdempotencyRequired


def canonical_digest(value) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def derive_generation_idempotency(*, user_id, subject_id, raw_key: str) -> str:
    if not isinstance(raw_key, str) or not 16 <= len(raw_key.encode()) <= 128:
        raise KeywordGenerationIdempotencyRequired
    master = settings.KEYWORD_GENERATION_IDEMPOTENCY_HMAC_KEY.encode()
    subkey = hmac.new(master, b"keyword-generation:idempotency:v1", hashlib.sha256).digest()
    scope = f"user={user_id}|subject={subject_id}|key={raw_key}"
    return hmac.new(subkey, scope.encode(), hashlib.sha256).hexdigest()
