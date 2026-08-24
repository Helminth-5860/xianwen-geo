from dataclasses import dataclass
from functools import lru_cache

from django.contrib.auth.hashers import check_password, make_password
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.request_ids import validate_request_id

from .models import LoginEvent, User
from .phone_numbers import phone_fingerprint
from .rate_limits import LoginRateLimiter, LoginRateLimitKeys
from .sms.purposes import SmsPurpose, parse_sms_purpose


class AccountAlreadyExists(Exception):
    pass


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
    from .sms.security import client_ip_address as trusted_client_ip_address

    return trusted_client_ip_address(request)


def request_user_agent(request) -> str:
    return (request.META.get("HTTP_USER_AGENT", "") or "")[:512]


@transaction.atomic
def record_login_event(
    *,
    normalized_phone: str,
    user: User | None,
    login_method: str,
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
        login_method=login_method,
        success=success,
        failure_reason=failure_reason,
        ip_address=client_ip_address(request),
        user_agent=request_user_agent(request),
        request_id=request_id,
    )


def record_password_login_event(
    *,
    normalized_phone: str,
    user: User | None,
    success: bool,
    failure_reason: str,
    request,
) -> LoginEvent:
    return record_login_event(
        normalized_phone=normalized_phone,
        user=user,
        login_method=LoginEvent.LoginMethod.PASSWORD,
        success=success,
        failure_reason=failure_reason,
        request=request,
    )


def rate_limit_keys(request, normalized_phone: str) -> LoginRateLimitKeys:
    from .rate_limits import login_rate_limit_keys

    return login_rate_limit_keys(normalized_phone, client_ip_address(request))


def login_rate_limiter() -> LoginRateLimiter:
    return LoginRateLimiter()


def verification_submission_limiter(purpose: SmsPurpose | str) -> LoginRateLimiter:
    resolved_purpose = parse_sms_purpose(purpose)
    return LoginRateLimiter(namespace=f"verification-{resolved_purpose.value}")


def should_deliver_sms(normalized_phone: str, purpose: SmsPurpose | str) -> bool:
    resolved_purpose = parse_sms_purpose(purpose)
    if resolved_purpose is SmsPurpose.REGISTER:
        return True
    user = User.objects.filter(phone=normalized_phone).first()
    if user is None or user.account_status == User.AccountStatus.CANCELLED:
        return False
    if resolved_purpose is SmsPurpose.LOGIN:
        from apps.admin_rbac.security import admin_identity

        if admin_identity(user):
            return False
    return True


def create_registered_user(
    *, phone: str, nickname: str, password: str, registration_ref: str
) -> User:
    if User.objects.filter(phone=phone).exists():
        raise AccountAlreadyExists
    try:
        with transaction.atomic():
            from apps.admin_rbac.models import CustomerAssignment
            from apps.admin_rbac.registration_links import resolve_registration_admin

            owner = resolve_registration_admin(registration_ref, for_update=True)
            user = User.objects.create_user(
                phone=phone,
                nickname=nickname,
                password=password,
                tenant=owner.user.tenant,
                account_status=User.AccountStatus.ACTIVE,
                is_active=True,
            )
            assignment = CustomerAssignment(
                customer=user,
                owner_admin=owner,
                assigned_at=timezone.now(),
            )
            assignment.full_clean()
            assignment.save()
            return user
    except IntegrityError as exc:
        raise AccountAlreadyExists from exc


def sms_login_user(normalized_phone: str) -> User | None:
    try:
        return User.objects.get(phone=normalized_phone)
    except User.DoesNotExist:
        return None


@transaction.atomic
def reset_user_password(*, normalized_phone: str, new_password: str) -> bool:
    try:
        user = User.objects.select_for_update().get(phone=normalized_phone)
    except User.DoesNotExist:
        return False
    if user.account_status == User.AccountStatus.CANCELLED:
        return False
    user.set_password(new_password)
    user.save(update_fields=["password", "updated_at"])
    return True
