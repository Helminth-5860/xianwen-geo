from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


class CredentialCryptoError(RuntimeError):
    pass


@lru_cache(maxsize=4)
def _fernet(key: str) -> Fernet:
    try:
        encoded = key.encode("ascii")
        return Fernet(encoded)
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise CredentialCryptoError("field encryption key is unavailable") from exc


def encrypt_secret(value: str) -> str:
    try:
        return (
            _fernet(settings.FIELD_ENCRYPTION_MASTER_KEY)
            .encrypt(value.encode("utf-8"))
            .decode("ascii")
        )
    except CredentialCryptoError:
        raise
    except Exception as exc:
        raise CredentialCryptoError("credential encryption failed") from exc


def decrypt_secret(token: str) -> str:
    try:
        raw = _fernet(settings.FIELD_ENCRYPTION_MASTER_KEY).decrypt(token.encode("ascii"))
        return raw.decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError, ValueError) as exc:
        raise CredentialCryptoError("credential decryption failed") from exc


def mask_secret(value: str) -> str:
    if len(value) < 8:
        return "********"
    return "********" + value[-4:]
