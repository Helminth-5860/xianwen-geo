import hashlib
import hmac
import json
from dataclasses import dataclass

from django.conf import settings

from .exceptions import FileIdempotencyKeyRequired

KEY_VERSION = 1


@dataclass(frozen=True)
class FileIdempotencyDigests:
    key_version: int
    key_digest: str
    request_digest: str


def canonical_digest(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _subkey(label: str) -> bytes:
    master = settings.FILE_IDEMPOTENCY_HMAC_KEY.encode("utf-8")
    return hmac.new(master, f"xianwen-file-v1:{label}".encode(), hashlib.sha256).digest()


def derive_file_digests(raw_key: str, *, user_id, payload: dict) -> FileIdempotencyDigests:
    key = (raw_key or "").strip()
    if not 16 <= len(key) <= 200 or any(ord(character) < 33 for character in key):
        raise FileIdempotencyKeyRequired
    request_digest = canonical_digest(payload)
    scope = f"{KEY_VERSION}|upload-intent|{user_id}"
    key_digest = hmac.new(
        _subkey("key-fingerprint"), f"{scope}|{key}".encode(), hashlib.sha256
    ).hexdigest()
    return FileIdempotencyDigests(KEY_VERSION, key_digest, request_digest)
