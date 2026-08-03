import hashlib
import hmac
import json
from dataclasses import dataclass

from django.conf import settings

KEY_VERSION = 1


class PlanChangeIdempotencyRequired(ValueError):
    code = "PLAN_CHANGE_IDEMPOTENCY_REQUIRED"


@dataclass(frozen=True)
class PlanChangeDigests:
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
    master = settings.PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY.encode("utf-8")
    return hmac.new(
        master,
        f"xianwen-plan-change-v1:{label}".encode(),
        hashlib.sha256,
    ).digest()


def _digest(label: str, value: str) -> str:
    return hmac.new(_subkey(label), value.encode("utf-8"), hashlib.sha256).hexdigest()


def derive_plan_change_digests(
    raw_key: str,
    *,
    operation: str,
    requester_id,
    target_id,
    request_payload: dict,
) -> PlanChangeDigests:
    key = (raw_key or "").strip()
    if not 16 <= len(key) <= 200 or any(ord(character) < 33 for character in key):
        raise PlanChangeIdempotencyRequired
    request_digest = canonical_digest(request_payload)
    stable_scope = f"{KEY_VERSION}|{operation}|{requester_id}|{target_id}"
    return PlanChangeDigests(
        key_version=KEY_VERSION,
        key_digest=_digest("key-fingerprint", f"{stable_scope}|{key}"),
        scope_digest=_digest(
            "operation-scope",
            f"{stable_scope}|{request_digest}|{key}",
        ),
        request_digest=request_digest,
    )
