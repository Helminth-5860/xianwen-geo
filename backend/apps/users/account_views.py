from django.contrib.auth import logout
from django.middleware.csrf import rotate_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_409_CONFLICT,
    HTTP_422_UNPROCESSABLE_ENTITY,
)
from rest_framework.views import APIView

from apps.core.error_codes import ErrorCode
from apps.core.responses import error_response

from .account_settings import (
    AccountCodeRateLimited,
    AccountCodeRateLimitUnavailable,
    CurrentPasswordInvalid,
    PasswordPolicyInvalid,
    PhoneAlreadyInUse,
    PhoneChangeTargetInvalid,
    PhoneVerificationInvalid,
    change_password,
    change_phone,
    consume_phone_code_send_limit,
    ensure_phone_change_target,
    revoke_other_sessions,
    update_appearance,
    update_profile,
)
from .authentication import SESSION_VERSION_KEY
from .models import Notification
from .permissions import IsOrdinaryAvailableUser
from .rate_limits import LoginRateLimitUnavailable
from .serializers import (
    AppearanceUpdateSerializer,
    CurrentUserSerializer,
    NotificationSerializer,
    PaginationSerializer,
    PasswordChangeSerializer,
    PhoneChangeSerializer,
    PhoneCodeSendSerializer,
    ProfileUpdateSerializer,
    SessionRevokeSerializer,
)
from .services import client_ip_address, login_rate_limiter, rate_limit_keys
from .sms.exceptions import SmsRateLimited, SmsServiceUnavailable
from .sms.service import send_verification_code
from .sms.tencent import SmsProviderError
from .status_services import mark_notification_read
from .views import _rate_limited, _service_unavailable, _sms_provider_failure


def _reauth_limiter(request):
    limiter = login_rate_limiter()
    limiter.namespace = "account-security-reauth"
    keys = rate_limit_keys(request, request.user.phone)
    try:
        limiter.ensure_allowed(keys)
    except PermissionError:
        return limiter, keys, _rate_limited(request)
    except LoginRateLimitUnavailable:
        return limiter, keys, _service_unavailable(request)
    return limiter, keys, None


def _register_reauth_failure(request, limiter, keys):
    try:
        if limiter.register_failure(keys):
            return _rate_limited(request)
    except LoginRateLimitUnavailable:
        return _service_unavailable(request)
    return None


def _clear_reauth_success(request, limiter, keys):
    try:
        limiter.clear_successful_combination(keys)
    except LoginRateLimitUnavailable:
        return _service_unavailable(request)
    return None


def _current_password_invalid(request):
    return error_response(
        ErrorCode.CURRENT_PASSWORD_INVALID,
        status_code=HTTP_422_UNPROCESSABLE_ENTITY,
        request=request,
    )


def _phone_in_use(request):
    return error_response(
        ErrorCode.PHONE_ALREADY_IN_USE,
        status_code=HTTP_409_CONFLICT,
        request=request,
    )


def _phone_target_invalid(request):
    return error_response(
        ErrorCode.PHONE_CHANGE_TARGET_INVALID,
        status_code=HTTP_409_CONFLICT,
        request=request,
    )


def _handle_current_password_failure(request, limiter, keys):
    limited = _register_reauth_failure(request, limiter, keys)
    return limited or _current_password_invalid(request)


@method_decorator(csrf_protect, name="dispatch")
class ProfileUpdateView(APIView):
    permission_classes = [IsOrdinaryAvailableUser]

    def patch(self, request):
        serializer = ProfileUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = update_profile(
            user_id=request.user.pk,
            nickname=serializer.validated_data["nickname"],
        )
        return Response(CurrentUserSerializer(user).data)


@method_decorator(csrf_protect, name="dispatch")
class PhoneCodeSendView(APIView):
    permission_classes = [IsOrdinaryAvailableUser]

    def post(self, request):
        serializer = PhoneCodeSendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        limiter, keys, blocked = _reauth_limiter(request)
        if blocked:
            return blocked
        if not request.user.check_password(data["current_password"]):
            return _handle_current_password_failure(request, limiter, keys)
        cleared = _clear_reauth_success(request, limiter, keys)
        if cleared:
            return cleared
        try:
            ensure_phone_change_target(
                user_id=request.user.pk,
                current_phone=request.user.phone,
                new_phone=data["phone"],
            )
        except PhoneChangeTargetInvalid:
            return _phone_target_invalid(request)
        except PhoneAlreadyInUse:
            return _phone_in_use(request)
        try:
            consume_phone_code_send_limit(
                user_id=request.user.pk,
                phone=data["phone"],
                ip_address=client_ip_address(request),
            )
        except AccountCodeRateLimited:
            return _rate_limited(request)
        except AccountCodeRateLimitUnavailable:
            return _service_unavailable(request)
        try:
            result = send_verification_code(
                data["phone"],
                "phone_change",
                client_ip_address(request),
            )
        except SmsRateLimited:
            return _rate_limited(request)
        except SmsProviderError as exc:
            return _sms_provider_failure(request, exc)
        except SmsServiceUnavailable:
            return _service_unavailable(request)
        return Response(
            {
                "sent": True,
                "expires_in": result.expires_in,
                "resend_after": result.resend_after,
            }
        )


@method_decorator(csrf_protect, name="dispatch")
class PhoneChangeView(APIView):
    permission_classes = [IsOrdinaryAvailableUser]

    def patch(self, request):
        serializer = PhoneChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        limiter, keys, blocked = _reauth_limiter(request)
        if blocked:
            return blocked
        try:
            change_phone(
                user_id=request.user.pk,
                new_phone=data["phone"],
                current_password=data["current_password"],
                code=data["code"],
            )
        except CurrentPasswordInvalid:
            return _handle_current_password_failure(request, limiter, keys)
        except PhoneVerificationInvalid:
            limited = _register_reauth_failure(request, limiter, keys)
            if limited:
                return limited
            return error_response(
                ErrorCode.VERIFICATION_CODE_INVALID,
                status_code=HTTP_422_UNPROCESSABLE_ENTITY,
                request=request,
            )
        except SmsServiceUnavailable:
            return _service_unavailable(request)
        except PhoneChangeTargetInvalid:
            cleared = _clear_reauth_success(request, limiter, keys)
            return cleared or _phone_target_invalid(request)
        except PhoneAlreadyInUse:
            cleared = _clear_reauth_success(request, limiter, keys)
            return cleared or _phone_in_use(request)
        logout(request)
        return Response({"changed": True, "reauthentication_required": True})


@method_decorator(csrf_protect, name="dispatch")
class PasswordChangeView(APIView):
    permission_classes = [IsOrdinaryAvailableUser]

    def patch(self, request):
        serializer = PasswordChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        limiter, keys, blocked = _reauth_limiter(request)
        if blocked:
            return blocked
        try:
            change_password(
                user_id=request.user.pk,
                current_password=data["current_password"],
                new_password=data["new_password"],
            )
        except CurrentPasswordInvalid:
            return _handle_current_password_failure(request, limiter, keys)
        except PasswordPolicyInvalid as exc:
            cleared = _clear_reauth_success(request, limiter, keys)
            if cleared:
                return cleared
            raise serializers.ValidationError({"new_password": exc.messages}) from exc
        logout(request)
        return Response({"changed": True, "reauthentication_required": True})


@method_decorator(csrf_protect, name="dispatch")
class AppearanceUpdateView(APIView):
    permission_classes = [IsOrdinaryAvailableUser]

    def patch(self, request):
        serializer = AppearanceUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = update_appearance(
            user_id=request.user.pk,
            mode=serializer.validated_data["mode"],
            accent=serializer.validated_data["accent"],
        )
        return Response(CurrentUserSerializer(user).data)


@method_decorator(csrf_protect, name="dispatch")
class SessionRevokeView(APIView):
    permission_classes = [IsOrdinaryAvailableUser]

    def post(self, request):
        serializer = SessionRevokeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        limiter, keys, blocked = _reauth_limiter(request)
        if blocked:
            return blocked
        if not request.user.check_password(serializer.validated_data["current_password"]):
            return _handle_current_password_failure(request, limiter, keys)
        cleared = _clear_reauth_success(request, limiter, keys)
        if cleared:
            return cleared
        try:
            user = revoke_other_sessions(
                user_id=request.user.pk,
                current_password=serializer.validated_data["current_password"],
            )
        except CurrentPasswordInvalid:
            return _handle_current_password_failure(request, limiter, keys)
        request.user = user
        request.session.cycle_key()
        request.session[SESSION_VERSION_KEY] = user.session_version
        rotate_token(request)
        return Response({"revoked": True})


class NotificationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query_serializer = PaginationSerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        query = query_serializer.validated_data
        notifications = Notification.objects.filter(recipient=request.user).order_by(
            "-created_at", "-id"
        )
        count = notifications.count()
        offset = (query["page"] - 1) * query["page_size"]
        items = notifications[offset : offset + query["page_size"]]
        return Response(
            {
                "results": NotificationSerializer(items, many=True).data,
                "pagination": {
                    "page": query["page"],
                    "page_size": query["page_size"],
                    "count": count,
                    "total_pages": (count + query["page_size"] - 1) // query["page_size"],
                },
            }
        )


@method_decorator(csrf_protect, name="dispatch")
class NotificationReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, notification_id):
        notification = mark_notification_read(
            user_id=request.user.pk,
            notification_id=notification_id,
        )
        return Response(NotificationSerializer(notification).data)
