import uuid
from math import ceil

from django.db.models import Q
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework import serializers as drf_serializers
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_409_CONFLICT,
    HTTP_422_UNPROCESSABLE_ENTITY,
)
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

from .models import Plan, PlanLimitDefinition, PlanVersion
from .serializers import (
    PlanCopyRequestSerializer,
    PlanCreateRequestSerializer,
    PlanDetailSerializer,
    PlanExpectedVersionRequestSerializer,
    PlanLimitDefinitionSerializer,
    PlanPublishRequestSerializer,
    PlanSummarySerializer,
    PlanUpdateRequestSerializer,
    PlanVersionCreateRequestSerializer,
    PlanVersionSerializer,
    PlanVersionUpdateRequestSerializer,
)
from .services import (
    PlanDomainError,
    public_plan_summary,
)


def _page(queryset, serializer, *, page, page_size):
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


def _pagination(request):
    try:
        page = max(int(request.query_params.get("page", 1)), 1)
        page_size = min(max(int(request.query_params.get("page_size", 20)), 1), 100)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"page": ["分页参数不正确。"]}) from exc
    return page, page_size


def _plan_or_404(plan_id):
    try:
        return (
            Plan.objects.exclude(code=Plan.INTERNAL_TEST_CODE)
            .select_related("current_published_version")
            .get(pk=plan_id)
        )
    except Plan.DoesNotExist as exc:
        raise NotFound from exc


def _version_or_404(version_id):
    try:
        return (
            PlanVersion.objects.exclude(plan__code=Plan.INTERNAL_TEST_CODE)
            .select_related("plan")
            .get(pk=version_id)
        )
    except PlanVersion.DoesNotExist as exc:
        raise NotFound from exc


PLAN_ERROR_STATUS = {
    "PLAN_VERSION_CONFLICT": HTTP_409_CONFLICT,
    "PLAN_STATE_CONFLICT": HTTP_409_CONFLICT,
    "PLAN_VERSION_STATE_CONFLICT": HTTP_409_CONFLICT,
    "PLAN_DRAFT_ALREADY_EXISTS": HTTP_409_CONFLICT,
    "PLAN_LIMIT_INVALID": HTTP_422_UNPROCESSABLE_ENTITY,
    "PLAN_MODEL_PERMISSION_INVALID": HTTP_422_UNPROCESSABLE_ENTITY,
    "PLAN_PUBLISH_VALIDATION_FAILED": HTTP_422_UNPROCESSABLE_ENTITY,
    "PLAN_IMMUTABLE": HTTP_409_CONFLICT,
}


def _domain_error_response(exc, request):
    code = ErrorCode(exc.code)
    return error_response(code, status_code=PLAN_ERROR_STATUS[exc.code], request=request)


def _perform(request, *, serializer, action_key, target_id, target_version, raw_payload):
    try:
        result = perform_risk_action(
            request=request,
            action_key=action_key,
            target_id=target_id,
            target_version=target_version,
            raw_payload=raw_payload,
            confirmed=serializer.validated_data.get("confirmed", False),
            current_password=serializer.validated_data.get("current_password", ""),
        )
    except (RiskError, AdminReauthFailed, AdminReauthRateLimited, AdminSecurityUnavailable) as exc:
        return risk_error_response(exc, request)
    except PlanDomainError as exc:
        return _domain_error_response(exc, request)
    return Response(result.data)


class AdminPlanListView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "plans.list"
    required_permissions_by_method = {"GET": "plans.list", "POST": "plans.create"}

    def get(self, request):
        queryset = Plan.objects.exclude(code=Plan.INTERNAL_TEST_CODE).select_related(
            "current_published_version"
        )
        status_value = request.query_params.get("status")
        if status_value:
            if status_value not in Plan.Status.values:
                raise ValidationError({"status": ["套餐状态不正确。"]})
            queryset = queryset.filter(status=status_value)
        keyword = request.query_params.get("keyword", "").strip()
        if keyword:
            queryset = queryset.filter(Q(code__icontains=keyword) | Q(name__icontains=keyword))
        page, page_size = _pagination(request)
        return Response(
            _page(
                queryset.order_by("sort_order", "id"),
                PlanSummarySerializer,
                page=page,
                page_size=page_size,
            )
        )

    @method_decorator(csrf_protect)
    def post(self, request):
        serializer = PlanCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        payload.pop("confirmed", None)
        payload.pop("current_password", None)
        return _perform(
            request,
            serializer=serializer,
            action_key="plan.create",
            target_id=uuid.uuid4(),
            target_version=0,
            raw_payload=payload,
        )


class AdminPlanDetailView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "plans.view"

    def get(self, request, plan_id):
        return Response(PlanDetailSerializer(_plan_or_404(plan_id)).data)

    @method_decorator(csrf_protect)
    def patch(self, request, plan_id):
        serializer = PlanUpdateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        expected = payload.pop("expected_version")
        payload.pop("confirmed", None)
        payload.pop("current_password", None)
        return _perform(
            request,
            serializer=serializer,
            action_key="plan.update",
            target_id=plan_id,
            target_version=expected,
            raw_payload=payload,
        )


class AdminPlanLimitDefinitionListView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "plan_limits.view"

    def get(self, request):
        rows = PlanLimitDefinition.objects.order_by("sort_order", "key")
        return Response(PlanLimitDefinitionSerializer(rows, many=True).data)


class AdminPlanVersionListView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "plan_versions.list"

    def get(self, request, plan_id):
        _plan_or_404(plan_id)
        rows = PlanVersion.objects.filter(plan_id=plan_id).order_by("-version_no")
        return Response(PlanVersionSerializer(rows, many=True).data)

    @method_decorator(csrf_protect)
    def post(self, request, plan_id):
        serializer = PlanVersionCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        expected = payload.pop("expected_plan_version")
        payload.pop("confirmed", None)
        payload.pop("current_password", None)
        return _perform(
            request,
            serializer=serializer,
            action_key="plan.version.create",
            target_id=plan_id,
            target_version=expected,
            raw_payload=payload,
        )


class AdminPlanVersionDetailView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "plan_versions.view"

    def get(self, request, version_id):
        return Response(PlanVersionSerializer(_version_or_404(version_id)).data)

    @method_decorator(csrf_protect)
    def patch(self, request, version_id):
        serializer = PlanVersionUpdateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        expected = payload.pop("expected_version")
        payload.pop("confirmed", None)
        payload.pop("current_password", None)
        return _perform(
            request,
            serializer=serializer,
            action_key="plan.version.update",
            target_id=version_id,
            target_version=expected,
            raw_payload=payload,
        )


class _PlanActionView(APIView):
    permission_classes = [HasAdminPermission]
    action_key = ""

    @method_decorator(csrf_protect)
    def post(self, request, plan_id):
        serializer = PlanExpectedVersionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return _perform(
            request,
            serializer=serializer,
            action_key=self.action_key,
            target_id=plan_id,
            target_version=serializer.validated_data["expected_version"],
            raw_payload={},
        )


class AdminPlanOnlineView(_PlanActionView):
    required_permission = "plans.online"
    action_key = "plan.online"


class AdminPlanOfflineView(_PlanActionView):
    required_permission = "plans.offline"
    action_key = "plan.offline"


class AdminPlanArchiveView(_PlanActionView):
    required_permission = "plans.archive"
    action_key = "plan.archive"


@method_decorator(csrf_protect, name="dispatch")
class AdminPlanCopyView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "plans.copy"

    def post(self, request, plan_id):
        serializer = PlanCopyRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        expected = payload.pop("expected_source_plan_version")
        payload.pop("confirmed", None)
        payload.pop("current_password", None)
        payload["new_plan_id"] = uuid.uuid4()
        return _perform(
            request,
            serializer=serializer,
            action_key="plan.copy",
            target_id=plan_id,
            target_version=expected,
            raw_payload=payload,
        )


class _VersionActionView(APIView):
    permission_classes = [HasAdminPermission]
    action_key = ""
    serializer_class: type[drf_serializers.Serializer] = PlanExpectedVersionRequestSerializer

    @method_decorator(csrf_protect)
    def post(self, request, version_id):
        _version_or_404(version_id)
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        expected = payload.pop("expected_version")
        payload.pop("confirmed", None)
        payload.pop("current_password", None)
        return _perform(
            request,
            serializer=serializer,
            action_key=self.action_key,
            target_id=version_id,
            target_version=expected,
            raw_payload=payload,
        )


class AdminPlanVersionPublishView(_VersionActionView):
    required_permission = "plan_versions.publish"
    action_key = "plan.version.publish"
    serializer_class = PlanPublishRequestSerializer


class AdminPlanVersionRetireView(_VersionActionView):
    required_permission = "plan_versions.retire"
    action_key = "plan.version.retire"


class PublicPlanListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        rows = (
            Plan.objects.select_related("current_published_version")
            .filter(status=Plan.Status.PUBLISHED)
            .order_by("sort_order", "id")
        )
        return Response([public_plan_summary(plan) for plan in rows])


class PublicPlanDetailView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, plan_id):
        try:
            plan = Plan.objects.select_related("current_published_version").get(
                pk=plan_id, status=Plan.Status.PUBLISHED
            )
        except Plan.DoesNotExist as exc:
            raise NotFound from exc
        return Response(public_plan_summary(plan))
