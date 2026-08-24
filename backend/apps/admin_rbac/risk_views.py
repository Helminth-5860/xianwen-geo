from math import ceil

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_403_FORBIDDEN,
    HTTP_409_CONFLICT,
    HTTP_422_UNPROCESSABLE_ENTITY,
    HTTP_500_INTERNAL_SERVER_ERROR,
)
from rest_framework.views import APIView

from apps.core.error_codes import ErrorCode
from apps.core.responses import error_response

from .models import AuditEvent, RiskAction, RiskPolicy
from .permissions import HasAdminPermission
from .risk_handlers import HANDLER_SPECS
from .risk_serializers import (
    AuditEventSerializer,
    RiskActionSerializer,
    RiskPolicySerializer,
    RiskPolicyUpdateSerializer,
)
from .risk_services import RiskError, update_risk_policy
from .security import AdminReauthFailed, AdminReauthRateLimited, AdminSecurityUnavailable

ERROR_STATUS = {
    "RISK_CONFIRMATION_REQUIRED": HTTP_422_UNPROCESSABLE_ENTITY,
    "RISK_POLICY_VERSION_CONFLICT": HTTP_409_CONFLICT,
    "RISK_SECURITY_MODE_NOT_SUPPORTED": HTTP_422_UNPROCESSABLE_ENTITY,
    "RISK_SECURITY_MODE_BELOW_MINIMUM": HTTP_422_UNPROCESSABLE_ENTITY,
    "RISK_TARGET_STALE": HTTP_409_CONFLICT,
    "RISK_PAYLOAD_INVALID": HTTP_422_UNPROCESSABLE_ENTITY,
    "RISK_ACTION_EXECUTION_FAILED": HTTP_500_INTERNAL_SERVER_ERROR,
}


def risk_error_response(exc, request):
    if isinstance(exc, AdminReauthFailed):
        return error_response(
            ErrorCode.ADMIN_REAUTH_FAILED, status_code=HTTP_403_FORBIDDEN, request=request
        )
    if isinstance(exc, AdminReauthRateLimited):
        return error_response(ErrorCode.RATE_LIMITED, status_code=429, request=request)
    if isinstance(exc, AdminSecurityUnavailable):
        return error_response(
            ErrorCode.SERVICE_TEMPORARILY_UNAVAILABLE, status_code=503, request=request
        )
    code = getattr(exc, "code", "RISK_ACTION_EXECUTION_FAILED")
    return error_response(ErrorCode(code), status_code=ERROR_STATUS[code], request=request)


def _page(queryset, serializer, request):
    try:
        page = max(int(request.query_params.get("page", 1)), 1)
        page_size = min(max(int(request.query_params.get("page_size", 20)), 1), 100)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"page": ["分页参数不正确。"]}) from exc
    count = queryset.count()
    offset = (page - 1) * page_size
    return {
        "results": serializer(queryset[offset : offset + page_size], many=True).data,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "count": count,
            "total_pages": ceil(count / page_size) if count else 0,
        },
    }


class RiskActionListView(APIView):
    required_permission = "admin.dashboard.view"
    permission_classes = [HasAdminPermission]

    def get(self, request):
        actions = RiskAction.objects.select_related("policy").filter(
            status=RiskAction.Status.ACTIVE
        )
        if not request.user.is_superuser:
            allowed = {
                key
                for key, spec in HANDLER_SPECS.items()
                if not spec.superuser_only
                and spec.permission_key in request.admin_context.permission_keys
            }
            actions = actions.filter(key__in=allowed)
        return Response(RiskActionSerializer(actions, many=True).data)


class RiskPolicyListView(APIView):
    required_permission = "risk_policy.view"
    permission_classes = [HasAdminPermission]

    def get(self, request):
        return Response(
            RiskPolicySerializer(
                RiskPolicy.objects.select_related("action").order_by("action_id"), many=True
            ).data
        )


@method_decorator(csrf_protect, name="dispatch")
class RiskPolicyDetailView(APIView):
    required_permission = "risk_policy.update"
    permission_classes = [HasAdminPermission]
    requires_step_up = True

    def patch(self, request, action_key):
        serializer = RiskPolicyUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            policy = update_risk_policy(
                request=request, action_key=action_key, **serializer.validated_data
            )
        except (
            RiskError,
            AdminReauthFailed,
            AdminReauthRateLimited,
            AdminSecurityUnavailable,
        ) as exc:
            return risk_error_response(exc, request)
        return Response(RiskPolicySerializer(policy).data)


class AuditEventListView(APIView):
    required_permission = "audit.list"
    permission_classes = [HasAdminPermission]

    def get(self, request):
        queryset = AuditEvent.objects.all()
        action_key = request.query_params.get("action_key")
        outcome = request.query_params.get("outcome")
        if action_key:
            queryset = queryset.filter(action_key=action_key[:100])
        if outcome:
            queryset = queryset.filter(outcome=outcome[:32])
        return Response(_page(queryset, AuditEventSerializer, request))


class AuditEventDetailView(APIView):
    required_permission = "audit.view"
    permission_classes = [HasAdminPermission]

    def get(self, request, event_id):
        try:
            event = AuditEvent.objects.get(pk=event_id)
        except AuditEvent.DoesNotExist as exc:
            raise NotFound from exc
        return Response(AuditEventSerializer(event).data, status=HTTP_200_OK)
