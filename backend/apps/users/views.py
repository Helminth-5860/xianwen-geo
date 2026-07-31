from django.contrib.auth import login, logout
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_401_UNAUTHORIZED,
    HTTP_429_TOO_MANY_REQUESTS,
    HTTP_503_SERVICE_UNAVAILABLE,
)
from rest_framework.views import APIView

from apps.core.error_codes import ErrorCode
from apps.core.responses import error_response

from .models import LoginEvent
from .rate_limits import LoginRateLimitUnavailable
from .serializers import CurrentUserSerializer, PasswordLoginSerializer, SmsSendSerializer
from .services import (
    authenticate_password,
    login_rate_limiter,
    rate_limit_keys,
    record_password_login_event,
)
from .sms.exceptions import SmsRateLimited, SmsServiceUnavailable
from .sms.security import client_ip_address
from .sms.service import send_verification_code

INVALID_CREDENTIALS_MESSAGE = "手机号或密码不正确"


@method_decorator(csrf_protect, name="dispatch")
class SmsSendView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SmsSendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = send_verification_code(
                serializer.validated_data["phone"],
                serializer.validated_data["purpose"],
                client_ip_address(request),
            )
        except SmsRateLimited:
            return error_response(
                ErrorCode.RATE_LIMITED,
                status_code=HTTP_429_TOO_MANY_REQUESTS,
                request=request,
            )
        except SmsServiceUnavailable:
            return error_response(
                ErrorCode.SERVICE_TEMPORARILY_UNAVAILABLE,
                status_code=HTTP_503_SERVICE_UNAVAILABLE,
                request=request,
            )
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
            return error_response(
                ErrorCode.RATE_LIMITED,
                status_code=HTTP_429_TOO_MANY_REQUESTS,
                request=request,
            )
        except LoginRateLimitUnavailable:
            record_password_login_event(
                normalized_phone=normalized_phone,
                user=None,
                success=False,
                failure_reason=LoginEvent.FailureReason.SERVICE_UNAVAILABLE,
                request=request,
            )
            return error_response(
                ErrorCode.SERVICE_TEMPORARILY_UNAVAILABLE,
                status_code=HTTP_503_SERVICE_UNAVAILABLE,
                request=request,
            )

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
                return error_response(
                    ErrorCode.SERVICE_TEMPORARILY_UNAVAILABLE,
                    status_code=HTTP_503_SERVICE_UNAVAILABLE,
                    request=request,
                )

            record_password_login_event(
                normalized_phone=normalized_phone,
                user=result.user,
                success=False,
                failure_reason=result.failure_reason,
                request=request,
            )
            if limited:
                return error_response(
                    ErrorCode.RATE_LIMITED,
                    status_code=HTTP_429_TOO_MANY_REQUESTS,
                    request=request,
                )
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
            return error_response(
                ErrorCode.SERVICE_TEMPORARILY_UNAVAILABLE,
                status_code=HTTP_503_SERVICE_UNAVAILABLE,
                request=request,
            )

        try:
            login(
                request,
                result.user,
                backend="django.contrib.auth.backends.ModelBackend",
            )
            request.session.set_expiry(0)
            record_password_login_event(
                normalized_phone=normalized_phone,
                user=result.user,
                success=True,
                failure_reason="",
                request=request,
            )
        except Exception:
            logout(request)
            raise
        return Response(CurrentUserSerializer(result.user).data)


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
