from math import ceil

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_409_CONFLICT,
)
from rest_framework.views import APIView

from apps.admin_rbac.permissions import HasAdminPermission
from apps.admin_rbac.risk_services import RiskError, perform_risk_action
from apps.admin_rbac.risk_views import risk_error_response
from apps.admin_rbac.scopes import scoped_customer_or_404, scoped_customers
from apps.admin_rbac.security import (
    AdminReauthFailed,
    AdminReauthRateLimited,
    AdminSecurityUnavailable,
)
from apps.core.error_codes import ErrorCode
from apps.core.responses import error_response

from .models import User
from .serializers import (
    AccountStatusActionSerializer,
    AdminUserDetailSerializer,
    AdminUserListQuerySerializer,
    AdminUserListSerializer,
    FreezeStatusActionSerializer,
    PaginationSerializer,
    UserStatusEventSerializer,
)
from .status_services import (
    AccountStateConflict,
    change_account_status,
)


def _business_users():
    return User.objects.filter(is_staff=False, is_superuser=False)


def _page_data(queryset, serializer_class, *, page: int, page_size: int) -> dict:
    count = queryset.count()
    offset = (page - 1) * page_size
    items = queryset[offset : offset + page_size]
    return {
        "results": serializer_class(items, many=True).data,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "count": count,
            "total_pages": ceil(count / page_size) if count else 0,
        },
    }


class AdminUserListView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "users.list"

    def get(self, request):
        query_serializer = AdminUserListQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        query = query_serializer.validated_data
        users = scoped_customers(request.user, request.admin_context)
        if "account_status" in query:
            users = users.filter(account_status=query["account_status"])
        if "phone" in query:
            users = users.filter(phone=query["phone"])
        users = users.order_by("created_at", "id")
        return Response(
            _page_data(
                users,
                AdminUserListSerializer,
                page=query["page"],
                page_size=query["page_size"],
            )
        )


class AdminUserDetailView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "users.view"

    def get(self, request, user_id):
        user = scoped_customer_or_404(request.user, request.admin_context, user_id)
        return Response(AdminUserDetailSerializer(user).data)


class AdminUserHistoryView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "users.history.view"

    def get(self, request, user_id):
        user = scoped_customer_or_404(request.user, request.admin_context, user_id)
        query_serializer = PaginationSerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        query = query_serializer.validated_data
        events = user.status_events.select_related("actor").order_by("created_at", "id")
        return Response(
            _page_data(
                events,
                UserStatusEventSerializer,
                page=query["page"],
                page_size=query["page_size"],
            )
        )


class _AdminAccountStatusView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "users.freeze"
    requires_step_up = True
    action = ""

    def post(self, request, user_id):
        scoped_customer_or_404(request.user, request.admin_context, user_id)
        serializer_class = (
            FreezeStatusActionSerializer
            if self.action == "freeze"
            else AccountStatusActionSerializer
        )
        serializer = serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            if self.action == "freeze":
                perform_risk_action(
                    request=request,
                    action_key="user.freeze",
                    target_id=user_id,
                    target_version=data["expected_version"],
                    raw_payload={"reason": data.get("reason", "")},
                    confirmed=data["confirmed"],
                    current_password=data["current_password"],
                )
                user = User.objects.get(pk=user_id)
            else:
                result = change_account_status(
                    actor_id=request.user.pk,
                    user_id=user_id,
                    action=self.action,
                    reason=data.get("reason", ""),
                    request_id=request.request_id,
                )
                user = result.user
        except (
            RiskError,
            AdminReauthFailed,
            AdminReauthRateLimited,
            AdminSecurityUnavailable,
        ) as exc:
            return risk_error_response(exc, request)
        except AccountStateConflict:
            return error_response(
                ErrorCode.ACCOUNT_STATE_CONFLICT,
                status_code=HTTP_409_CONFLICT,
                request=request,
            )
        return Response(AdminUserDetailSerializer(user).data)


@method_decorator(csrf_protect, name="dispatch")
class AdminUserFreezeView(_AdminAccountStatusView):
    action = "freeze"


@method_decorator(csrf_protect, name="dispatch")
class AdminUserUnfreezeView(_AdminAccountStatusView):
    action = "unfreeze"
