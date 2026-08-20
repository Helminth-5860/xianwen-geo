from __future__ import annotations

import hashlib
import hmac
import json

from django.conf import settings

KEY_VERSION = 1


def canonical_digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def derive_geo_idempotency(*, namespace: str, user_id, subject_id, raw_key: str) -> str:
    key = (raw_key or "").strip()
    if not 16 <= len(key) <= 200 or any(ord(character) < 33 for character in key):
        raise ValueError("Invalid Idempotency-Key")
    if not namespace or not namespace.replace("-", "").isalnum():
        raise ValueError("Invalid idempotency namespace")
    master = settings.GEO_DETECTION_IDEMPOTENCY_HMAC_KEY.encode("utf-8")
    subkey = hmac.new(master, f"geo-{namespace}:idempotency:v1".encode(), hashlib.sha256).digest()
    message = f"{KEY_VERSION}:{user_id}:{subject_id}:{key}".encode()
    return hmac.new(subkey, message, hashlib.sha256).hexdigest()


def derive_detection_idempotency(*, user_id, subject_id, raw_key: str) -> str:
    return derive_geo_idempotency(
        namespace="detection",
        user_id=user_id,
        subject_id=subject_id,
        raw_key=raw_key,
    )
