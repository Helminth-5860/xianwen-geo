import re
import secrets
from dataclasses import dataclass
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError

from ..phone_numbers import normalize_phone
from .exceptions import SmsServiceUnavailable
from .providers import SmsProvider, get_sms_provider
from .purposes import SmsPurpose, parse_sms_purpose
from .security import (
    combination_fingerprint,
    ip_fingerprint,
    phone_fingerprint,
    verification_code_digest,
)
from .store import (
    RedisSmsVerificationStore,
    SmsVerificationStore,
    sms_redis_keys,
)

SMS_CODE_PATTERN = re.compile(r"^\d{6}$")


@dataclass(frozen=True)
class SmsSendResult:
    expires_in: int
    resend_after: int


def generate_verification_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def send_verification_code(
    phone: str,
    purpose: SmsPurpose | str,
    ip_address: str,
    *,
    provider: SmsProvider | None = None,
    store: SmsVerificationStore | None = None,
    suppress_delivery: bool = False,
) -> SmsSendResult:
    normalized_phone = normalize_phone(phone)
    resolved_purpose = parse_sms_purpose(purpose)
    resolved_provider = provider or get_sms_provider()
    if not resolved_provider.locally_available:
        raise SmsServiceUnavailable

    resolved_store = store or RedisSmsVerificationStore()
    phone_fp = phone_fingerprint(normalized_phone)
    ip_fp = ip_fingerprint(ip_address)
    combination_fp = combination_fingerprint(normalized_phone, ip_address)
    keys = sms_redis_keys(phone_fp, ip_fp, combination_fp, resolved_purpose)
    if suppress_delivery:
        resolved_store.reserve_suppressed(keys)
        return SmsSendResult(
            expires_in=settings.SMS_CODE_TTL_SECONDS,
            resend_after=settings.SMS_RESEND_COOLDOWN_SECONDS,
        )

    generation_id = str(uuid4())
    code = generate_verification_code()
    code_digest = verification_code_digest(
        normalized_phone,
        resolved_purpose,
        generation_id,
        code,
    )

    resolved_store.reserve(keys, generation_id, code_digest)
    try:
        resolved_provider.send_verification_code(
            phone=normalized_phone,
            purpose=resolved_purpose,
            code=code,
            expires_in=settings.SMS_CODE_TTL_SECONDS,
        )
    except Exception as exc:
        try:
            resolved_store.invalidate(keys.code, generation_id)
        except SmsServiceUnavailable:
            pass
        raise SmsServiceUnavailable from exc

    if not resolved_store.activate(keys.code, generation_id):
        raise SmsServiceUnavailable
    return SmsSendResult(
        expires_in=settings.SMS_CODE_TTL_SECONDS,
        resend_after=settings.SMS_RESEND_COOLDOWN_SECONDS,
    )


def verify_and_consume(
    phone: str,
    purpose: SmsPurpose | str,
    code: str,
    *,
    store: SmsVerificationStore | None = None,
) -> bool:
    try:
        normalized_phone = normalize_phone(phone)
        resolved_purpose = parse_sms_purpose(purpose)
    except (DjangoValidationError, ValueError):
        return False
    if not isinstance(code, str) or SMS_CODE_PATTERN.fullmatch(code) is None:
        return False

    resolved_store = store or RedisSmsVerificationStore()
    phone_fp = phone_fingerprint(normalized_phone)
    code_key = f"auth:sms:v1:code:{phone_fp}:{resolved_purpose.value}"
    generation_id = resolved_store.active_generation(code_key)
    if generation_id is None:
        return False
    digest = verification_code_digest(
        normalized_phone,
        resolved_purpose,
        generation_id,
        code,
    )
    return resolved_store.verify_and_consume(code_key, generation_id, digest)
