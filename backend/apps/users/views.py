from django.contrib.auth import login, logout
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_201_CREATED,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_409_CONFLICT,
    HTTP_422_UNPROCESSABLE_ENTITY,
    HTTP_429_TOO_MANY_REQUESTS,
    HTTP_503_SERVICE_UNAVAILABLE,
)
from rest_framework.views import APIView

from apps.core.error_codes import ErrorCode
from apps.core.responses import error_response

from .models import LoginEvent, User
from .rate_limits import LoginRateLimitUnavailable
from .serializers import (
    CurrentUserSerializer,
    PasswordLoginSerializer,
    PasswordResetSerializer,
    RegistrationSerializer,
    SmsLoginSerializer,
    SmsSendSerializer,
)
from .services import (
    AccountAlreadyExists,
    authenticate_password,
    create_registered_user,
    login_rate_limiter,
    rate_limit_keys,
    record_login_event,
    record_password_login_event,
    reset_user_password,
    should_deliver_sms,
    sms_login_user,
    verification_submission_limiter,
)
from .sms.exceptions import SmsRateLimited, SmsServiceUnavailable
from .sms.security import client_ip_address
from .sms.service import send_verification_code, verify_and_consume

INVALID_CREDENTIALS_MESSAGE = "手机号或密码不正确"
SMS_CREDENTIALS_MESSAGE = "手机号或短信验证码不正确"


def _service_unavailable(request):
    return error_response(
        ErrorCode.SERVICE_TEMPORARILY_UNAVAILABLE,
        status_code=HTTP_503_SERVICE_UNAVAILABLE,
        request=request,
    )


def _rate_limited(request):
    return error_response(
        ErrorCode.RATE_LIMITED,
        status_code=HTTP_429_TOO_MANY_REQUESTS,
        request=request,
    )


def _ensure_submission_allowed(request, limiter, keys):
    try:
        limiter.ensure_allowed(keys)
    except PermissionError:
        return _rate_limited(request)
    except LoginRateLimitUnavailable:
        return _service_unavailable(request)
    return None


def _register_invalid_submission(request, limiter, keys):
    try:
        if limiter.register_failure(keys):
            return _rate_limited(request)
    except LoginRateLimitUnavailable:
        return _service_unavailable(request)
    return None


def _clear_valid_submission(request, limiter, keys):
    try:
        limiter.clear_successful_combination(keys)
    except LoginRateLimitUnavailable:
        return _service_unavailable(request)
    return None


def _start_browser_session(request, user: User) -> None:
    login(
        request,
        user,
        backend="django.contrib.auth.backends.ModelBackend",
    )
    request.session.set_expiry(0)


@method_decorator(csrf_protect, name="dispatch")
class SmsSendView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SmsSendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        normalized_phone = serializer.validated_data["phone"]
        purpose = serializer.validated_data["purpose"]
        deliver = should_deliver_sms(normalized_phone, purpose)
        try:
            result = send_verification_code(
                normalized_phone,
                purpose,
                client_ip_address(request),
                suppress_delivery=not deliver,
            )
        except SmsRateLimited:
            return _rate_limited(request)
        except SmsServiceUnavailable:
            return _service_unavailable(request)
        return Response(
            {
                "sent": True,
                "expires_in": result.expires_in,
                "resend_after": result.resend_after,
            }
        )


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfTokenView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"csrf_token": get_token(request)})


@method_decorator(csrf_protect, name="dispatch")
class RegistrationView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        normalized_phone = data["phone"]
        limiter = verification_submission_limiter("register")
        keys = rate_limit_keys(request, normalized_phone)
        blocked = _ensure_submission_allowed(request, limiter, keys)
        if blocked:
            return blocked

        try:
            verified = verify_and_consume(normalized_phone, "register", data["sms_code"])
        except SmsServiceUnavailable:
            return _service_unavailable(request)
        if not verified:
            limited = _register_invalid_submission(request, limiter, keys)
            if limited:
                return limited
            return error_response(
                ErrorCode.VERIFICATION_CODE_INVALID,
                status_code=HTTP_422_UNPROCESSABLE_ENTITY,
                request=request,
            )

        unavailable = _clear_valid_submission(request, limiter, keys)
        if unavailable:
            return unavailable
        try:
            user = create_registered_user(
                phone=normalized_phone,
                nickname=data["nickname"],
                password=data["password"],
            )
        except AccountAlreadyExists:
            return error_response(
                ErrorCode.ACCOUNT_ALREADY_EXISTS,
                status_code=HTTP_409_CONFLICT,
                request=request,
            )

        try:
            _start_browser_session(request, user)
        except Exception:
            logout(request)
            raise
        return Response(CurrentUserSerializer(user).data, status=HTTP_201_CREATED)


@method_decorator(csrf_protect, name="dispatch")
class PasswordLoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        normalized_phone = serializer.validated_data["phone"]
        limiter = login_rate_limiter()
        keys = rate_limit_keys(request, normalized_phone)

        try:
            limiter.ensure_allowed(keys)
        except PermissionError:
            record_password_login_event(
                normalized_phone=normalized_phone,
                user=None,
                success=False,
                failure_reason=LoginEvent.FailureReason.RATE_LIMITED,
                request=request,
            )
            return _rate_limited(request)
        except LoginRateLimitUnavailable:
            record_password_login_event(
                normalized_phone=normalized_phone,
                user=None,
                success=False,
                failure_reason=LoginEvent.FailureReason.SERVICE_UNAVAILABLE,
                request=request,
            )
            return _service_unavailable(request)

        result = authenticate_password(
            normalized_phone,
            serializer.validated_data["password"],
        )
        if not result.succeeded:
            try:
                limited = limiter.register_failure(keys)
            except LoginRateLimitUnavailable:
                record_password_login_event(
                    normalized_phone=normalized_phone,
                    user=result.user,
                    success=False,
                    failure_reason=LoginEvent.FailureReason.SERVICE_UNAVAILABLE,
                    request=request,
                )
                return _service_unavailable(request)

            record_password_login_event(
                normalized_phone=normalized_phone,
                user=result.user,
                success=False,
                failure_reason=result.failure_reason,
                request=request,
            )
            if limited:
                return _rate_limited(request)
            return error_response(
                ErrorCode.AUTH_REQUIRED,
                status_code=HTTP_401_UNAUTHORIZED,
                request=request,
                message=INVALID_CREDENTIALS_MESSAGE,
            )

        try:
            limiter.clear_successful_combination(keys)
        except LoginRateLimitUnavailable:
            record_password_login_event(
                normalized_phone=normalized_phone,
                user=result.user,
                success=False,
                failure_reason=LoginEvent.FailureReason.SERVICE_UNAVAILABLE,
                request=request,
            )
            return _service_unavailable(request)

        user = result.user
        if user is None:
            raise RuntimeError("成功认证缺少用户。")
        try:
            _start_browser_session(request, user)
            record_password_login_event(
                normalized_phone=normalized_phone,
                user=user,
                success=True,
                failure_reason="",
                request=request,
            )
        except Exception:
            logout(request)
            raise
        return Response(CurrentUserSerializer(user).data)


@method_decorator(csrf_protect, name="dispatch")
class SmsLoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SmsLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        normalized_phone = data["phone"]
        limiter = verification_submission_limiter("login")
        keys = rate_limit_keys(request, normalized_phone)
        blocked = _ensure_submission_allowed(request, limiter, keys)
        if blocked:
            return blocked

        try:
            verified = verify_and_consume(normalized_phone, "login", data["sms_code"])
        except SmsServiceUnavailable:
            return _service_unavailable(request)
        if not verified:
            limited = _register_invalid_submission(request, limiter, keys)
            record_login_event(
                normalized_phone=normalized_phone,
                user=None,
                login_method=LoginEvent.LoginMethod.SMS,
                success=False,
                failure_reason=LoginEvent.FailureReason.INVALID_CREDENTIALS,
                request=request,
            )
            if limited:
                return limited
            return error_response(
                ErrorCode.AUTH_CREDENTIALS_INVALID,
                status_code=HTTP_401_UNAUTHORIZED,
                request=request,
                message=SMS_CREDENTIALS_MESSAGE,
            )

        user = sms_login_user(normalized_phone)
        if user is None:
            limited = _register_invalid_submission(request, limiter, keys)
            record_login_event(
                normalized_phone=normalized_phone,
                user=None,
                login_method=LoginEvent.LoginMethod.SMS,
                success=False,
                failure_reason=LoginEvent.FailureReason.INVALID_CREDENTIALS,
                request=request,
            )
            if limited:
                return limited
            return error_response(
                ErrorCode.AUTH_CREDENTIALS_INVALID,
                status_code=HTTP_401_UNAUTHORIZED,
                request=request,
                message=SMS_CREDENTIALS_MESSAGE,
            )

        unavailable = _clear_valid_submission(request, limiter, keys)
        if unavailable:
            return unavailable
        if user.account_status in {User.AccountStatus.FROZEN, User.AccountStatus.CANCELLED}:
            record_login_event(
                normalized_phone=normalized_phone,
                user=user,
                login_method=LoginEvent.LoginMethod.SMS,
                success=False,
                failure_reason=LoginEvent.FailureReason.INACTIVE_ACCOUNT,
                request=request,
            )
            return error_response(
                ErrorCode.ACCOUNT_UNAVAILABLE,
                status_code=HTTP_403_FORBIDDEN,
                request=request,
            )

        try:
            _start_browser_session(request, user)
            record_login_event(
                normalized_phone=normalized_phone,
                user=user,
                login_method=LoginEvent.LoginMethod.SMS,
                success=True,
                failure_reason="",
                request=request,
            )
        except Exception:
            logout(request)
            raise
        return Response(CurrentUserSerializer(user).data)


@method_decorator(csrf_protect, name="dispatch")
class PasswordResetView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        normalized_phone = data["phone"]
        limiter = verification_submission_limiter("password_reset")
        keys = rate_limit_keys(request, normalized_phone)
        blocked = _ensure_submission_allowed(request, limiter, keys)
        if blocked:
            return blocked

        try:
            verified = verify_and_consume(
                normalized_phone,
                "password_reset",
                data["sms_code"],
            )
        except SmsServiceUnavailable:
            return _service_unavailable(request)
        if not verified:
            limited = _register_invalid_submission(request, limiter, keys)
            if limited:
                return limited
            return error_response(
                ErrorCode.VERIFICATION_CODE_INVALID,
                status_code=HTTP_422_UNPROCESSABLE_ENTITY,
                request=request,
            )

        unavailable = _clear_valid_submission(request, limiter, keys)
        if unavailable:
            return unavailable
        reset_user_password(
            normalized_phone=normalized_phone,
            new_password=data["new_password"],
        )
        return Response({"reset": True})


@method_decorator(csrf_protect, name="dispatch")
class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logout(request)
        return Response({"logged_out": True})


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(CurrentUserSerializer(request.user).data)
