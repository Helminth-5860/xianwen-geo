import hashlib
import hmac
import json
from dataclasses import dataclass

from django.conf import settings

from .exceptions import QuotaIdempotencyRequired

KEY_VERSION = 1


@dataclass(frozen=True)
class IdempotencyDigests:
    key_version: int
    key_digest: str
    scope_digest: str
    request_digest: str


def canonical_digest(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _subkey(label: str) -> bytes:
    master = settings.QUOTA_IDEMPOTENCY_HMAC_KEY.encode("utf-8")
    return hmac.new(master, f"xianwen-quota-v1:{label}".encode(), hashlib.sha256).digest()


def _digest(label: str, value: str) -> str:
    return hmac.new(_subkey(label), value.encode("utf-8"), hashlib.sha256).hexdigest()


def derive_idempotency_digests(
    raw_key: str,
    *,
    operation: str,
    user_id,
    account_id,
    business_type: str,
    business_id,
    request_payload: dict,
) -> IdempotencyDigests:
    key = (raw_key or "").strip()
    if not 16 <= len(key) <= 200 or any(ord(character) < 33 for character in key):
        raise QuotaIdempotencyRequired
    request_digest = canonical_digest(request_payload)
    stable_scope = f"{KEY_VERSION}|{operation}|{user_id}"
    key_digest = _digest("key-fingerprint", f"{stable_scope}|{key}")
    full_scope = f"{stable_scope}|{account_id}|{business_type}|{business_id}|{request_digest}|{key}"
    return IdempotencyDigests(
        key_version=KEY_VERSION,
        key_digest=key_digest,
        scope_digest=_digest("operation-scope", full_scope),
        request_digest=request_digest,
    )


def system_idempotency_digests(
    *, operation: str, user_id, account_id, business_type: str, business_id, request_payload: dict
) -> IdempotencyDigests:
    request_digest = canonical_digest(request_payload)
    stable_scope = f"{KEY_VERSION}|system|{operation}|{user_id}|{account_id}|{business_id}"
    return IdempotencyDigests(
        key_version=KEY_VERSION,
        key_digest=_digest("system-key", stable_scope),
        scope_digest=_digest("system-scope", f"{stable_scope}|{business_type}|{request_digest}"),
        request_digest=request_digest,
    )
