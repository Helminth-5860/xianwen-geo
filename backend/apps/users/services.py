from dataclasses import dataclass
from functools import lru_cache

from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction

from apps.core.request_ids import validate_request_id

from .models import LoginEvent, User
from .phone_numbers import phone_fingerprint
from .rate_limits import LoginRateLimiter, LoginRateLimitKeys


@dataclass(frozen=True)
class PasswordAuthenticationResult:
    user: User | None
    failure_reason: str

    @property
    def succeeded(self) -> bool:
        return self.user is not None and not self.failure_reason


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    return make_password("xianwen-dummy-password-not-a-credential")


def authenticate_password(normalized_phone: str, password: str) -> PasswordAuthenticationResult:
    try:
        user = User.objects.get(phone=normalized_phone)
    except User.DoesNotExist:
        check_password(password, _dummy_password_hash())
        return PasswordAuthenticationResult(
            user=None,
            failure_reason=LoginEvent.FailureReason.INVALID_CREDENTIALS,
        )

    if not user.check_password(password):
        return PasswordAuthenticationResult(
            user=user,
            failure_reason=LoginEvent.FailureReason.INVALID_CREDENTIALS,
        )
    if not user.is_active:
        return PasswordAuthenticationResult(
            user=user,
            failure_reason=LoginEvent.FailureReason.INACTIVE_ACCOUNT,
        )
    return PasswordAuthenticationResult(user=user, failure_reason="")


def client_ip_address(request) -> str:
    return request.META.get("REMOTE_ADDR", "") or "0.0.0.0"


def request_user_agent(request) -> str:
    return (request.META.get("HTTP_USER_AGENT", "") or "")[:512]


@transaction.atomic
def record_password_login_event(
    *,
    normalized_phone: str,
    user: User | None,
    success: bool,
    failure_reason: str,
    request,
) -> LoginEvent:
    request_id = validate_request_id(getattr(request, "request_id", ""))
    if request_id is None:
        raise ValueError("登录事件必须包含规范 request_id。")
    return LoginEvent.objects.create(
        user=user,
        phone_fingerprint=phone_fingerprint(normalized_phone),
        login_method=LoginEvent.LoginMethod.PASSWORD,
        success=success,
        failure_reason=failure_reason,
        ip_address=client_ip_address(request),
        user_agent=request_user_agent(request),
        request_id=request_id,
    )


def rate_limit_keys(request, normalized_phone: str) -> LoginRateLimitKeys:
    from .rate_limits import login_rate_limit_keys

    return login_rate_limit_keys(normalized_phone, client_ip_address(request))


def login_rate_limiter() -> LoginRateLimiter:
    return LoginRateLimiter()
