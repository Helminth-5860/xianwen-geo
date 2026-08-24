from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_201_CREATED,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_409_CONFLICT,
    HTTP_429_TOO_MANY_REQUESTS,
    HTTP_503_SERVICE_UNAVAILABLE,
)
from rest_framework.views import APIView

from apps.core.error_codes import ErrorCode
from apps.core.responses import error_response
from apps.users.rate_limits import LoginRateLimitUnavailable
from apps.users.serializers import CurrentUserSerializer
from apps.users.services import (
    authenticate_password,
    login_rate_limiter,
    rate_limit_keys,
    record_password_login_event,
)
from apps.users.sms.exceptions import SmsRateLimited, SmsServiceUnavailable

from .models import (
    AdminProfile,
    AdminRole,
    RoleIpAllowlistEntry,
    SuperuserIpAllowlistEntry,
    SuperuserSecurityPolicy,
)
from .permissions import HasAdminSession, HasSuperuserAdminSession
from .risk_services import RiskError, perform_risk_action
from .risk_views import risk_error_response
from .security import (
    AdminChallengeExpired,
    AdminChallengeInvalid,
    AdminChallengeReplayed,
    AdminIpNotAllowed,
    AdminReauthFailed,
    AdminReauthRateLimited,
    AdminSecurityUnavailable,
    LockoutConfirmationRequired,
    SecurityPolicyVersionConflict,
    clear_admin_session,
    create_admin_challenge,
    grant_admin_step_up,
    record_security_event,
    security_snapshot,
    send_admin_second_factor,
    start_admin_session,
    verify_admin_second_factor,
)
from .serializers import (
    AdminChallengeVerifySerializer,
    AdminPasswordLoginSerializer,
    IpAllowlistCreateSerializer,
    IpAllowlistUpdateSerializer,
    RoleIpAllowlistSerializer,
    RoleSecurityUpdateSerializer,
    SuperuserIpAllowlistSerializer,
    SuperuserSecurityPolicySerializer,
    SuperuserSecurityUpdateSerializer,
    VersionSerializer,
)


def _admin_failure(code, status_code, request):
    return error_response(code, status_code=status_code, request=request)


def _challenge_error(exc, request):
    if isinstance(exc, AdminChallengeExpired):
        return _admin_failure(
            ErrorCode.ADMIN_AUTH_CHALLENGE_EXPIRED, HTTP_401_UNAUTHORIZED, request
        )
    if isinstance(exc, (AdminSecurityUnavailable, SmsServiceUnavailable)):
        return _admin_failure(
            ErrorCode.SERVICE_TEMPORARILY_UNAVAILABLE, HTTP_503_SERVICE_UNAVAILABLE, request
        )
    return _admin_failure(ErrorCode.ADMIN_AUTH_CHALLENGE_INVALID, HTTP_401_UNAUTHORIZED, request)


def _policy_error(exc, request):
    if isinstance(exc, SecurityPolicyVersionConflict):
        return _admin_failure(
            ErrorCode.SECURITY_POLICY_VERSION_CONFLICT, HTTP_409_CONFLICT, request
        )
    if isinstance(exc, LockoutConfirmationRequired):
        return _admin_failure(
            ErrorCode.IP_ALLOWLIST_LOCKOUT_CONFIRMATION_REQUIRED, HTTP_409_CONFLICT, request
        )
    if isinstance(exc, AdminReauthFailed):
        return _admin_failure(ErrorCode.ADMIN_REAUTH_FAILED, HTTP_403_FORBIDDEN, request)
    if isinstance(exc, AdminReauthRateLimited):
        return _admin_failure(ErrorCode.RATE_LIMITED, HTTP_429_TOO_MANY_REQUESTS, request)
    if isinstance(exc, AdminSecurityUnavailable):
        return _admin_failure(
            ErrorCode.SERVICE_TEMPORARILY_UNAVAILABLE, HTTP_503_SERVICE_UNAVAILABLE, request
        )
    if isinstance(exc, AdminIpNotAllowed):
        return _admin_failure(ErrorCode.ADMIN_IP_NOT_ALLOWED, HTTP_409_CONFLICT, request)
    raise exc


@method_decorator(csrf_protect, name="dispatch")
class AdminPasswordLoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = AdminPasswordLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone = serializer.validated_data["phone"]
        limiter = login_rate_limiter()
        keys = rate_limit_keys(request, phone)
        try:
            limiter.ensure_allowed(keys)
        except PermissionError:
            return _admin_failure(ErrorCode.RATE_LIMITED, HTTP_429_TOO_MANY_REQUESTS, request)
        except LoginRateLimitUnavailable:
            return _admin_failure(
                ErrorCode.SERVICE_TEMPORARILY_UNAVAILABLE, HTTP_503_SERVICE_UNAVAILABLE, request
            )
        result = authenticate_password(phone, serializer.validated_data["password"])
        if not result.succeeded or result.user is None:
            try:
                limited = limiter.register_failure(keys)
            except LoginRateLimitUnavailable:
                return _admin_failure(
                    ErrorCode.SERVICE_TEMPORARILY_UNAVAILABLE,
                    HTTP_503_SERVICE_UNAVAILABLE,
                    request,
                )
            record_password_login_event(
                normalized_phone=phone,
                user=result.user,
                success=False,
                failure_reason=result.failure_reason,
                request=request,
            )
            record_security_event(
                request=request,
                event_type="password_step_failed",
                subject=result.user,
                failure_reason="invalid_credentials",
            )
            return _admin_failure(
                ErrorCode.RATE_LIMITED if limited else ErrorCode.AUTH_CREDENTIALS_INVALID,
                HTTP_429_TOO_MANY_REQUESTS if limited else HTTP_401_UNAUTHORIZED,
                request,
            )
        user = result.user
        try:
            snapshot = security_snapshot(user, request)
        except AdminIpNotAllowed:
            record_security_event(
                request=request, event_type="ip_denied", subject=user, failure_reason="ip_denied"
            )
            return _admin_failure(ErrorCode.ADMIN_IP_NOT_ALLOWED, HTTP_403_FORBIDDEN, request)
        except AdminSecurityUnavailable:
            return _admin_failure(
                ErrorCode.SERVICE_TEMPORARILY_UNAVAILABLE, HTTP_503_SERVICE_UNAVAILABLE, request
            )
        except AdminChallengeInvalid:
            return _admin_failure(ErrorCode.ACCOUNT_UNAVAILABLE, HTTP_403_FORBIDDEN, request)
        try:
            limiter.clear_successful_combination(keys)
        except LoginRateLimitUnavailable:
            return _admin_failure(
                ErrorCode.SERVICE_TEMPORARILY_UNAVAILABLE, HTTP_503_SERVICE_UNAVAILABLE, request
            )
        record_security_event(
            request=request, event_type="password_step_succeeded", subject=user, snapshot=snapshot
        )
        start_admin_session(request, snapshot, "password")
        record_password_login_event(
            normalized_phone=phone,
            user=user,
            success=True,
            failure_reason="",
            request=request,
        )
        record_security_event(
            request=request, event_type="admin_login_succeeded", subject=user, snapshot=snapshot
        )
        return Response({"requires_2fa": False, "user": CurrentUserSerializer(user).data})


@method_decorator(csrf_protect, name="dispatch")
class AdminStepUpChallengeView(APIView):
    permission_classes = [HasAdminSession]

    def post(self, request):
        try:
            snapshot = request.admin_security_snapshot
            challenge_id = create_admin_challenge(snapshot, request)
            send_admin_second_factor(challenge_id, request)
            record_security_event(
                request=request,
                event_type="step_up_challenge_sent",
                actor=request.user,
                subject=snapshot.user,
                snapshot=snapshot,
            )
        except SmsRateLimited:
            return _admin_failure(ErrorCode.RATE_LIMITED, HTTP_429_TOO_MANY_REQUESTS, request)
        except (
            AdminChallengeExpired,
            AdminChallengeInvalid,
            AdminChallengeReplayed,
            AdminSecurityUnavailable,
            SmsServiceUnavailable,
        ) as exc:
            return _challenge_error(exc, request)
        return Response(
            {
                "challenge_id": challenge_id,
                "sent": True,
                "expires_in": settings.ADMIN_CHALLENGE_TTL_SECONDS,
                "resend_after": settings.SMS_RESEND_COOLDOWN_SECONDS,
            },
            status=HTTP_201_CREATED,
        )


@method_decorator(csrf_protect, name="dispatch")
class AdminStepUpVerifyView(APIView):
    permission_classes = [HasAdminSession]

    def post(self, request):
        serializer = AdminChallengeVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            snapshot = verify_admin_second_factor(
                serializer.validated_data["challenge_id"],
                serializer.validated_data["sms_code"],
                request,
            )
        except (
            AdminChallengeExpired,
            AdminChallengeInvalid,
            AdminChallengeReplayed,
            AdminSecurityUnavailable,
        ) as exc:
            event_type = (
                "challenge_expired"
                if isinstance(exc, AdminChallengeExpired)
                else "challenge_replayed"
                if isinstance(exc, AdminChallengeReplayed)
                else "second_factor_failed"
            )
            record_security_event(
                request=request,
                event_type=event_type,
                actor=request.user,
                subject=request.user,
                failure_reason="challenge_invalid",
            )
            return _challenge_error(exc, request)
        grant_admin_step_up(request, snapshot)
        record_security_event(
            request=request,
            event_type="admin_step_up_succeeded",
            actor=request.user,
            subject=snapshot.user,
            snapshot=snapshot,
        )
        return Response({"verified": True, "expires_in": settings.ADMIN_CHALLENGE_TTL_SECONDS})


@method_decorator(csrf_protect, name="dispatch")
class AdminLogoutView(APIView):
    permission_classes = [HasAdminSession]

    def post(self, request):
        user = request.user
        record_security_event(
            request=request,
            event_type="admin_logout",
            actor=user,
            subject=user,
            snapshot=request.admin_security_snapshot,
        )
        clear_admin_session(request)
        return Response({"logged_out": True})


class RoleSecurityView(APIView):
    required_permission = "roles.update"
    permission_classes = [HasSuperuserAdminSession]

    def get(self, request, role_id):
        try:
            role = AdminRole.objects.get(pk=role_id)
        except AdminRole.DoesNotExist as exc:
            raise NotFound from exc
        return Response(
            {
                "require_sms_2fa": role.require_sms_2fa,
                "ip_allowlist_enabled": role.ip_allowlist_enabled,
                "security_version": role.security_version,
            }
        )

    @method_decorator(csrf_protect)
    def patch(self, request, role_id):
        serializer = RoleSecurityUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            perform_risk_action(
                request=request,
                action_key="role.security.update",
                target_id=role_id,
                target_version=data["expected_security_version"],
                raw_payload={
                    key: value
                    for key, value in data.items()
                    if key not in {"current_password", "expected_security_version"}
                },
                current_password=data["current_password"],
            )
            role = AdminRole.objects.get(pk=role_id)
        except RiskError as exc:
            return risk_error_response(exc, request)
        except AdminRole.DoesNotExist as exc:
            raise NotFound from exc
        except (
            SecurityPolicyVersionConflict,
            LockoutConfirmationRequired,
            AdminReauthFailed,
            AdminReauthRateLimited,
            AdminSecurityUnavailable,
            AdminIpNotAllowed,
        ) as exc:
            return _policy_error(exc, request)
        return Response(
            {
                "require_sms_2fa": role.require_sms_2fa,
                "ip_allowlist_enabled": role.ip_allowlist_enabled,
                "security_version": role.security_version,
            }
        )


class RoleIpAllowlistView(APIView):
    required_permission = "roles.update"
    permission_classes = [HasSuperuserAdminSession]

    def get(self, request, role_id):
        try:
            role = AdminRole.objects.get(pk=role_id)
        except AdminRole.DoesNotExist as exc:
            raise NotFound from exc
        return Response(RoleIpAllowlistSerializer(role.ip_allowlist_entries.all(), many=True).data)

    @method_decorator(csrf_protect)
    def post(self, request, role_id):
        serializer = IpAllowlistCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            result = perform_risk_action(
                request=request,
                action_key="role.ip_allowlist.update",
                target_id=role_id,
                target_version=data["expected_security_version"],
                raw_payload={
                    "operation": "create",
                    "network_cidr": data["network_cidr"],
                    "label": data.get("label", ""),
                    "confirm_lockout": data["confirm_lockout"],
                },
                current_password=data["current_password"],
            )
            entry = RoleIpAllowlistEntry.objects.get(pk=result.data["entry_id"], role_id=role_id)
            role = AdminRole.objects.get(pk=role_id)
        except RiskError as exc:
            return risk_error_response(exc, request)
        except AdminRole.DoesNotExist as exc:
            raise NotFound from exc
        except (
            SecurityPolicyVersionConflict,
            LockoutConfirmationRequired,
            AdminReauthFailed,
            AdminReauthRateLimited,
            AdminSecurityUnavailable,
            AdminIpNotAllowed,
        ) as exc:
            return _policy_error(exc, request)
        return Response(
            {
                "entry": RoleIpAllowlistSerializer(entry).data,
                "security_version": role.security_version,
            },
            status=HTTP_201_CREATED,
        )


class RoleIpAllowlistDetailView(APIView):
    required_permission = "roles.update"
    permission_classes = [HasSuperuserAdminSession]

    @method_decorator(csrf_protect)
    def patch(self, request, role_id, entry_id):
        serializer = IpAllowlistUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            perform_risk_action(
                request=request,
                action_key="role.ip_allowlist.update",
                target_id=role_id,
                target_version=data["expected_security_version"],
                raw_payload={
                    "operation": "update",
                    "entry_id": entry_id,
                    "status": data["status"],
                    "label": data.get("label", ""),
                    "confirm_lockout": data["confirm_lockout"],
                },
                current_password=data["current_password"],
            )
            entry = RoleIpAllowlistEntry.objects.get(pk=entry_id, role_id=role_id)
            role = AdminRole.objects.get(pk=role_id)
        except RiskError as exc:
            return risk_error_response(exc, request)
        except (AdminRole.DoesNotExist, RoleIpAllowlistEntry.DoesNotExist) as exc:
            raise NotFound from exc
        except (
            SecurityPolicyVersionConflict,
            LockoutConfirmationRequired,
            AdminReauthFailed,
            AdminReauthRateLimited,
            AdminSecurityUnavailable,
            AdminIpNotAllowed,
        ) as exc:
            return _policy_error(exc, request)
        return Response(
            {
                "entry": RoleIpAllowlistSerializer(entry).data,
                "security_version": role.security_version,
            }
        )


class SuperuserSecurityView(APIView):
    required_permission = "admins.update"
    permission_classes = [HasSuperuserAdminSession]

    def get(self, request):
        if not request.user.is_superuser:
            return _admin_failure(ErrorCode.PERMISSION_DENIED, HTTP_403_FORBIDDEN, request)
        policy, _ = SuperuserSecurityPolicy.objects.get_or_create(user=request.user)
        return Response(SuperuserSecurityPolicySerializer(policy).data)

    @method_decorator(csrf_protect)
    def patch(self, request):
        serializer = SuperuserSecurityUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            perform_risk_action(
                request=request,
                action_key="superuser.ip_allowlist.update",
                target_id=request.user.pk,
                target_version=data["expected_security_version"],
                raw_payload={
                    "operation": "policy",
                    "ip_allowlist_enabled": data["ip_allowlist_enabled"],
                    "confirm_lockout": data["confirm_lockout"],
                },
                current_password=data["current_password"],
            )
            policy = SuperuserSecurityPolicy.objects.get(user=request.user)
        except RiskError as exc:
            return risk_error_response(exc, request)
        except (
            SecurityPolicyVersionConflict,
            LockoutConfirmationRequired,
            AdminReauthFailed,
            AdminReauthRateLimited,
            AdminSecurityUnavailable,
            AdminIpNotAllowed,
        ) as exc:
            return _policy_error(exc, request)
        return Response(SuperuserSecurityPolicySerializer(policy).data)


class SuperuserIpAllowlistView(APIView):
    required_permission = "admins.update"
    permission_classes = [HasSuperuserAdminSession]

    def get(self, request):
        if not request.user.is_superuser:
            return _admin_failure(ErrorCode.PERMISSION_DENIED, HTTP_403_FORBIDDEN, request)
        policy, _ = SuperuserSecurityPolicy.objects.get_or_create(user=request.user)
        return Response(
            SuperuserIpAllowlistSerializer(policy.ip_allowlist_entries.all(), many=True).data
        )

    @method_decorator(csrf_protect)
    def post(self, request):
        serializer = IpAllowlistCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            result = perform_risk_action(
                request=request,
                action_key="superuser.ip_allowlist.update",
                target_id=request.user.pk,
                target_version=data["expected_security_version"],
                raw_payload={
                    "operation": "create",
                    "network_cidr": data["network_cidr"],
                    "label": data.get("label", ""),
                    "confirm_lockout": data["confirm_lockout"],
                },
                current_password=data["current_password"],
            )
            entry = SuperuserIpAllowlistEntry.objects.get(pk=result.data["entry_id"])
            policy = SuperuserSecurityPolicy.objects.get(user=request.user)
        except RiskError as exc:
            return risk_error_response(exc, request)
        except (
            SecurityPolicyVersionConflict,
            LockoutConfirmationRequired,
            AdminReauthFailed,
            AdminReauthRateLimited,
            AdminSecurityUnavailable,
            AdminIpNotAllowed,
        ) as exc:
            return _policy_error(exc, request)
        return Response(
            {
                "entry": SuperuserIpAllowlistSerializer(entry).data,
                "security_version": policy.security_version,
            },
            status=HTTP_201_CREATED,
        )


class SuperuserIpAllowlistDetailView(APIView):
    required_permission = "admins.update"
    permission_classes = [HasSuperuserAdminSession]

    @method_decorator(csrf_protect)
    def patch(self, request, entry_id):
        serializer = IpAllowlistUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            perform_risk_action(
                request=request,
                action_key="superuser.ip_allowlist.update",
                target_id=request.user.pk,
                target_version=data["expected_security_version"],
                raw_payload={
                    "operation": "update",
                    "entry_id": entry_id,
                    "status": data["status"],
                    "label": data.get("label", ""),
                    "confirm_lockout": data["confirm_lockout"],
                },
                current_password=data["current_password"],
            )
            entry = SuperuserIpAllowlistEntry.objects.get(pk=entry_id)
            policy = SuperuserSecurityPolicy.objects.get(user=request.user)
        except RiskError as exc:
            return risk_error_response(exc, request)
        except SuperuserIpAllowlistEntry.DoesNotExist as exc:
            raise NotFound from exc
        except (
            SecurityPolicyVersionConflict,
            LockoutConfirmationRequired,
            AdminReauthFailed,
            AdminReauthRateLimited,
            AdminSecurityUnavailable,
            AdminIpNotAllowed,
        ) as exc:
            return _policy_error(exc, request)
        return Response(
            {
                "entry": SuperuserIpAllowlistSerializer(entry).data,
                "security_version": policy.security_version,
            }
        )


@method_decorator(csrf_protect, name="dispatch")
class AdminForceLogoutView(APIView):
    required_permission = "admins.disable"
    permission_classes = [HasSuperuserAdminSession]

    def post(self, request, profile_id):
        if not request.user.is_superuser:
            return _admin_failure(ErrorCode.PERMISSION_DENIED, HTTP_403_FORBIDDEN, request)
        serializer = VersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            result = perform_risk_action(
                request=request,
                action_key="admin.force_logout",
                target_id=profile_id,
                target_version=data["expected_version"],
                raw_payload={},
                confirmed=data["confirmed"],
                current_password=data["current_password"],
            )
        except (
            RiskError,
            AdminReauthFailed,
            AdminReauthRateLimited,
            AdminSecurityUnavailable,
        ) as exc:
            return risk_error_response(exc, request)
        except AdminProfile.DoesNotExist as exc:
            raise NotFound from exc
        return Response(result.data)
