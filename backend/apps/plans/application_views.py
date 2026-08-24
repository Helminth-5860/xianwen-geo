from math import ceil

from django.db.models import Q
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_201_CREATED
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

from .application_serializers import (
    PlanApplicationAdminActionSerializer,
    PlanApplicationAdminDetailSerializer,
    PlanApplicationAdminListSerializer,
    PlanApplicationCancelSerializer,
    PlanApplicationCreateSerializer,
    PlanApplicationUserSerializer,
)
from .application_services import (
    PlanApplicationAlreadyOpen,
    PlanApplicationError,
    cancel_application,
    create_application,
    scoped_application_or_404,
    scoped_plan_applications,
    user_application_or_404,
)
from .models import PlanApplication

APPLICATION_ERROR_STATUS = {
    "PLAN_APPLICATION_NOT_ELIGIBLE": 403,
    "PLAN_APPLICATION_PLAN_UNAVAILABLE": 409,
    "PLAN_APPLICATION_ALREADY_OPEN": 409,
    "PLAN_APPLICATION_STATE_CONFLICT": 409,
    "PLAN_APPLICATION_VERSION_CONFLICT": 409,
    "PLAN_APPLICATION_VERSION_MISMATCH": 409,
    "PLAN_APPLICATION_NOTE_INVALID": 422,
    "IDEMPOTENCY_KEY_REQUIRED": 422,
    "IDEMPOTENCY_CONFLICT": 409,
    "PLAN_APPLICATION_IMMUTABLE": 409,
}


def application_error_response(exc, request):
    details = {}
    if isinstance(exc, PlanApplicationAlreadyOpen) and exc.application is not None:
        details = {
            "existing_application_id": str(exc.application.pk),
            "status": exc.application.status,
        }
    return error_response(
        ErrorCode(exc.code),
        status_code=APPLICATION_ERROR_STATUS[exc.code],
        details=details,
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


@method_decorator(csrf_protect, name="dispatch")
class PlanApplicationListCreateView(APIView):
    def get(self, request):
        queryset = PlanApplication.objects.filter(applicant=request.user).prefetch_related("events")
        status_value = request.query_params.get("status")
        if status_value:
            if status_value not in PlanApplication.Status.values:
                raise ValidationError({"status": ["申请状态不正确。"]})
            queryset = queryset.filter(status=status_value)
        return Response(_page(queryset, PlanApplicationUserSerializer, request))

    def post(self, request):
        serializer = PlanApplicationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = create_application(
                applicant=request.user,
                plan_id=serializer.validated_data["plan_id"],
                plan_version_id=serializer.validated_data["plan_version_id"],
                user_note=serializer.validated_data["user_note"],
                idempotency_key=request.headers.get("Idempotency-Key"),
                request_id=request.request_id,
            )
        except PlanApplicationError as exc:
            return application_error_response(exc, request)
        return Response(
            PlanApplicationUserSerializer(result.application).data,
            status=HTTP_200_OK if result.replayed else HTTP_201_CREATED,
        )


class PlanApplicationDetailView(APIView):
    def get(self, request, application_id):
        application = user_application_or_404(request.user, application_id)
        return Response(PlanApplicationUserSerializer(application).data)


@method_decorator(csrf_protect, name="dispatch")
class PlanApplicationCancelView(APIView):
    def post(self, request, application_id):
        serializer = PlanApplicationCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            application = cancel_application(
                user=request.user,
                application_id=application_id,
                expected_version=serializer.validated_data["expected_version"],
                request_id=request.request_id,
            )
        except PlanApplicationError as exc:
            return application_error_response(exc, request)
        return Response(PlanApplicationUserSerializer(application).data)


class AdminPlanApplicationListView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "plan_applications.list"

    def get(self, request):
        queryset = scoped_plan_applications(request.user, request.admin_context)
        status_value = request.query_params.get("status")
        if status_value:
            if status_value not in PlanApplication.Status.values:
                raise ValidationError({"status": ["申请状态不正确。"]})
            queryset = queryset.filter(status=status_value)
        plan_id = request.query_params.get("plan_id")
        if plan_id:
            queryset = queryset.filter(plan_id=plan_id)
        phone = request.query_params.get("phone", "").strip()
        if phone:
            queryset = queryset.filter(applicant__phone=phone)
        keyword = request.query_params.get("keyword", "").strip()
        if keyword:
            queryset = queryset.filter(
                Q(applicant__nickname__icontains=keyword) | Q(plan__name__icontains=keyword)
            )
        return Response(_page(queryset, PlanApplicationAdminListSerializer, request))


class AdminPlanApplicationDetailView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "plan_applications.view"

    def get(self, request, application_id):
        application = scoped_application_or_404(request.user, request.admin_context, application_id)
        return Response(PlanApplicationAdminDetailSerializer(application).data)


class _AdminPlanApplicationActionView(APIView):
    permission_classes = [HasAdminPermission]
    action_key = ""

    @method_decorator(csrf_protect)
    def post(self, request, application_id):
        serializer = PlanApplicationAdminActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = perform_risk_action(
                request=request,
                action_key=self.action_key,
                target_id=application_id,
                target_version=serializer.validated_data["expected_version"],
                raw_payload={},
                confirmed=serializer.validated_data["confirmed"],
                current_password=serializer.validated_data["current_password"],
            )
        except PlanApplicationError as exc:
            return application_error_response(exc, request)
        except (
            RiskError,
            AdminReauthFailed,
            AdminReauthRateLimited,
            AdminSecurityUnavailable,
        ) as exc:
            return risk_error_response(exc, request)
        return Response(result.data, status=HTTP_200_OK)


class AdminPlanApplicationContactView(_AdminPlanApplicationActionView):
    required_permission = "plan_applications.contact"
    action_key = "plan_application.contact"


class AdminPlanApplicationCloseView(_AdminPlanApplicationActionView):
    required_permission = "plan_applications.close"
    action_key = "plan_application.close"
