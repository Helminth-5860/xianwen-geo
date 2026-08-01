from math import ceil

from django.db.models import Q
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_202_ACCEPTED
from rest_framework.views import APIView

from apps.admin_rbac.permissions import HasAdminPermission
from apps.admin_rbac.risk_services import RiskError, perform_risk_action
from apps.admin_rbac.risk_views import risk_error_response
from apps.admin_rbac.security import (
    AdminReauthFailed,
    AdminReauthRateLimited,
    AdminSecurityUnavailable,
)
from apps.core.error_codes import ErrorCode
from apps.core.responses import error_response

from .application_services import scoped_application_or_404
from .models import Subscription
from .subscription_serializers import (
    AdminSubscriptionDetailSerializer,
    AdminSubscriptionListSerializer,
    CurrentSubscriptionSerializer,
    GrantTrialRequestSerializer,
    OpenSubscriptionRequestSerializer,
    TerminateSubscriptionRequestSerializer,
)
from .subscription_services import (
    SubscriptionError,
    current_subscription,
    scoped_subscription_or_404,
    scoped_subscriptions,
)

SUBSCRIPTION_ERROR_STATUS = {
    "SUBSCRIPTION_NOT_ELIGIBLE": 403,
    "SUBSCRIPTION_ALREADY_ACTIVE": 409,
    "SUBSCRIPTION_STATE_CONFLICT": 409,
    "SUBSCRIPTION_VERSION_CONFLICT": 409,
    "SUBSCRIPTION_PLAN_UNAVAILABLE": 409,
    "SUBSCRIPTION_PLAN_VERSION_MISMATCH": 409,
    "SUBSCRIPTION_TRIAL_ALREADY_GRANTED": 409,
    "SUBSCRIPTION_CONFIRMATION_REQUIRED": 422,
    "SUBSCRIPTION_OVERRIDE_FORBIDDEN": 403,
    "SUBSCRIPTION_NOTE_INVALID": 422,
}


def subscription_error_response(exc, request):
    return error_response(
        ErrorCode(exc.code),
        status_code=SUBSCRIPTION_ERROR_STATUS[exc.code],
        request=request,
    )


def _pagination(request):
    try:
        page = max(int(request.query_params.get("page", 1)), 1)
        page_size = min(max(int(request.query_params.get("page_size", 20)), 1), 100)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"page": ["分页参数不正确。"]}) from exc
    return page, page_size


def _page(queryset, serializer, request):
    page, page_size = _pagination(request)
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


class CurrentSubscriptionView(APIView):
    def get(self, request):
        subscription = current_subscription(request.user)
        return Response(
            {
                "current": (
                    CurrentSubscriptionSerializer(subscription).data
                    if subscription is not None
                    else None
                )
            }
        )


class AdminSubscriptionListView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "subscriptions.list"

    def get(self, request):
        queryset = scoped_subscriptions(request.user, request.admin_context)
        status_value = request.query_params.get("status")
        if status_value:
            if status_value not in Subscription.Status.values:
                raise ValidationError({"status": ["订阅状态不正确。"]})
            queryset = queryset.filter(status=status_value)
        plan_id = request.query_params.get("plan_id")
        if plan_id:
            queryset = queryset.filter(plan_id=plan_id)
        user_id = request.query_params.get("user_id")
        if user_id:
            queryset = queryset.filter(user_id=user_id)
        keyword = request.query_params.get("keyword", "").strip()
        if keyword:
            queryset = queryset.filter(
                Q(user__nickname__icontains=keyword) | Q(plan__name__icontains=keyword)
            )
        return Response(_page(queryset, AdminSubscriptionListSerializer, request))


class AdminSubscriptionDetailView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "subscriptions.view"

    def get(self, request, subscription_id):
        subscription = scoped_subscription_or_404(
            request.user, request.admin_context, subscription_id
        )
        return Response(AdminSubscriptionDetailSerializer(subscription).data)


def _perform(request, *, action_key, target_id, target_version, raw_payload):
    try:
        result = perform_risk_action(
            request=request,
            action_key=action_key,
            target_id=target_id,
            target_version=target_version,
            raw_payload=raw_payload,
        )
    except SubscriptionError as exc:
        return subscription_error_response(exc, request)
    except (
        RiskError,
        AdminReauthFailed,
        AdminReauthRateLimited,
        AdminSecurityUnavailable,
    ) as exc:
        return risk_error_response(exc, request)
    return Response(
        result.data,
        status=HTTP_202_ACCEPTED if result.approval_required else HTTP_200_OK,
    )


class AdminOpenSubscriptionView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "subscriptions.open"

    @method_decorator(csrf_protect)
    def post(self, request, application_id):
        serializer = OpenSubscriptionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        selected_version_id = payload.get("selected_plan_version_id")
        if selected_version_id is not None:
            application = scoped_application_or_404(
                request.user, request.admin_context, application_id
            )
            if (
                selected_version_id != application.requested_plan_version_id
                and "subscriptions.override_version" not in request.admin_context.permission_keys
            ):
                raise PermissionDenied
        expected_version = payload.pop("expected_version")
        return _perform(
            request,
            action_key="subscription.open",
            target_id=application_id,
            target_version=expected_version,
            raw_payload=payload,
        )


class AdminGrantTrialView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "subscriptions.grant_trial"

    @method_decorator(csrf_protect)
    def post(self, request, user_id):
        serializer = GrantTrialRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        expected_version = payload.pop("expected_version")
        return _perform(
            request,
            action_key="subscription.grant_trial",
            target_id=user_id,
            target_version=expected_version,
            raw_payload=payload,
        )


class AdminTerminateSubscriptionView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "subscriptions.terminate"

    @method_decorator(csrf_protect)
    def post(self, request, subscription_id):
        serializer = TerminateSubscriptionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        expected_version = payload.pop("expected_version")
        return _perform(
            request,
            action_key="subscription.terminate",
            target_id=subscription_id,
            target_version=expected_version,
            raw_payload=payload,
        )
