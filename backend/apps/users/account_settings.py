from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction

from .models import User
from .phone_numbers import hmac_fingerprint
from .sms.service import verify_and_consume


class CurrentPasswordInvalid(Exception):
    pass


class PhoneChangeTargetInvalid(Exception):
    pass


class PhoneAlreadyInUse(Exception):
    pass


class PhoneVerificationInvalid(Exception):
    pass


class PasswordPolicyInvalid(Exception):
    def __init__(self, messages: list[str]):
        super().__init__()
        self.messages = messages


class AccountCodeRateLimited(Exception):
    pass


class AccountCodeRateLimitUnavailable(Exception):
    pass


@dataclass(frozen=True)
class _RateLimitScope:
    name: str
    fingerprint: str
    limit: int
    window_seconds: int


def _increment_with_window(key: str, *, limit: int, window_seconds: int) -> None:
    if cache.add(key, 1, timeout=window_seconds):
        count = 1
    else:
        count = cache.incr(key)
    if count > limit:
        raise AccountCodeRateLimited


def consume_phone_code_send_limit(*, user_id, phone: str, ip_address: str) -> None:
    user_value = str(user_id)
    scopes = (
        _RateLimitScope(
            "user",
            hmac_fingerprint("phone-change-user", user_value),
            settings.SMS_LIMIT_PHONE_COUNT,
            settings.SMS_LIMIT_PHONE_WINDOW_SECONDS,
        ),
        _RateLimitScope(
            "phone",
            hmac_fingerprint("phone-change-phone", phone),
            settings.SMS_LIMIT_PHONE_COUNT,
            settings.SMS_LIMIT_PHONE_WINDOW_SECONDS,
        ),
        _RateLimitScope(
            "ip",
            hmac_fingerprint("phone-change-ip", ip_address),
            settings.SMS_LIMIT_IP_COUNT,
            settings.SMS_LIMIT_IP_WINDOW_SECONDS,
        ),
        _RateLimitScope(
            "combination",
            hmac_fingerprint(
                "phone-change-combination",
                f"{user_value}|{ip_address}|{phone}",
            ),
            settings.SMS_LIMIT_COMBINATION_COUNT,
            settings.SMS_LIMIT_COMBINATION_WINDOW_SECONDS,
        ),
    )
    try:
        for scope in scopes:
            _increment_with_window(
                f"auth:phone-change-code:v1:{scope.name}:{scope.fingerprint}",
                limit=scope.limit,
                window_seconds=scope.window_seconds,
            )
    except AccountCodeRateLimited:
        raise
    except Exception as exc:
        raise AccountCodeRateLimitUnavailable from exc


def ensure_phone_change_target(*, user_id, current_phone: str, new_phone: str) -> None:
    if new_phone == current_phone:
        raise PhoneChangeTargetInvalid
    if User.objects.filter(phone=new_phone).exclude(pk=user_id).exists():
        raise PhoneAlreadyInUse


def update_profile(*, user_id, nickname: str) -> User:
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user_id)
        user.nickname = nickname
        user.save(update_fields=("nickname", "updated_at"))
        return user


def update_appearance(*, user_id, mode: str, accent: str) -> User:
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user_id)
        user.appearance_mode = mode
        user.appearance_accent = accent
        user.save(update_fields=("appearance_mode", "appearance_accent", "updated_at"))
        return user


def change_phone(
    *,
    user_id,
    new_phone: str,
    current_password: str,
    code: str,
) -> User:
    try:
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=user_id)
            if not user.check_password(current_password):
                raise CurrentPasswordInvalid
            ensure_phone_change_target(
                user_id=user.pk,
                current_phone=user.phone,
                new_phone=new_phone,
            )
            if not verify_and_consume(new_phone, "phone_change", code):
                raise PhoneVerificationInvalid
            user.phone = new_phone
            user.session_version += 1
            user.save(update_fields=("phone", "session_version", "updated_at"))
            return user
    except IntegrityError as exc:
        raise PhoneAlreadyInUse from exc


def change_password(*, user_id, current_password: str, new_password: str) -> User:
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user_id)
        if not user.check_password(current_password):
            raise CurrentPasswordInvalid
        if user.check_password(new_password):
            raise PasswordPolicyInvalid(["新密码不能与当前密码相同。"])
        try:
            validate_password(new_password, user)
        except DjangoValidationError as exc:
            raise PasswordPolicyInvalid(list(exc.messages)) from exc
        user.set_password(new_password)
        user.session_version += 1
        user.save(update_fields=("password", "session_version", "updated_at"))
        return user


def revoke_other_sessions(*, user_id, current_password: str) -> User:
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user_id)
        if not user.check_password(current_password):
            raise CurrentPasswordInvalid
        user.session_version += 1
        user.save(update_fields=("session_version", "updated_at"))
        return user
