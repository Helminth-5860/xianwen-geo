from __future__ import annotations

import base64
import hashlib
import json
import secrets
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


class PublishingCredentialError(ValueError):
    pass


def _fernet() -> Fernet:
    raw_key = getattr(settings, "PUBLISHING_CREDENTIAL_ENCRYPTION_KEY", "").strip()
    if raw_key:
        try:
            return Fernet(raw_key.encode("ascii"))
        except (ValueError, TypeError) as exc:
            raise PublishingCredentialError("PUBLISHING_CREDENTIAL_ENCRYPTION_KEY 配置无效") from exc

    seed = f"{settings.SECRET_KEY}:xianwen-publishing-v1".encode()
    derived = base64.urlsafe_b64encode(hashlib.sha256(seed).digest())
    return Fernet(derived)


def encrypt_secret(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict) or not payload:
        raise PublishingCredentialError("授权凭证不能为空")
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return _fernet().encrypt(raw).decode("ascii")


def decrypt_secret(ciphertext: str) -> dict[str, Any]:
    if not ciphertext:
        raise PublishingCredentialError("授权凭证不存在")
    try:
        raw = _fernet().decrypt(ciphertext.encode("ascii"))
        data = json.loads(raw.decode("utf-8"))
    except (InvalidToken, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublishingCredentialError("授权凭证无法读取") from exc
    if not isinstance(data, dict):
        raise PublishingCredentialError("授权凭证格式无效")
    return data


def issue_one_time_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    return token, digest


def digest_one_time_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
