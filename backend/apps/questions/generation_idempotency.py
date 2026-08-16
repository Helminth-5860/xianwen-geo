import hashlib
import hmac
import json

from django.conf import settings


def canonical_digest(value) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def derive_question_generation_idempotency(*, user_id, subject_id, raw_key: str) -> str:
    if not isinstance(raw_key, str) or not (16 <= len(raw_key) <= 200):
        raise ValueError("Invalid Idempotency-Key")
    master = settings.QUESTION_GENERATION_IDEMPOTENCY_HMAC_KEY.encode("utf-8")
    subkey = hmac.new(master, b"question-generation:idempotency:v1", hashlib.sha256).digest()
    message = f"{user_id}:{subject_id}:{raw_key}".encode()
    return hmac.new(subkey, message, hashlib.sha256).hexdigest()
