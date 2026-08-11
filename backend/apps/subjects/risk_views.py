import uuid
from math import ceil

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_202_ACCEPTED,
    HTTP_409_CONFLICT,
    HTTP_422_UNPROCESSABLE_ENTITY,
    HTTP_503_SERVICE_UNAVAILABLE,
)
from rest_framework.views import APIView

from apps.admin_rbac.permissions import HasAdminPermission
from apps.admin_rbac.risk_services import RiskError, perform_risk_action
from apps.admin_rbac.risk_views import risk_error_response
from apps.core.error_codes import ErrorCode
from apps.core.responses import error_response

from .models import SubjectReview, SubjectRiskRule, SubjectRiskType
from .risk_serializers import (
    CatalogPublishSerializer,
    CatalogRevisionSerializer,
    ReviewDecisionSerializer,
    ReviewSerializer,
    RiskRuleCreateSerializer,
    RiskRuleSerializer,
    RiskRuleUpdateSerializer,
    RiskTypeCreateSerializer,
    RiskTypeSerializer,
    RiskTypeUpdateSerializer,
)
from .risk_services import (
    SubjectRiskError,
    catalog_state,
    create_risk_rule,
    create_risk_type,
    decide_review,
    draft_catalog_binding,
    scoped_review_or_404,
    scoped_reviews,
    update_risk_rule,
    update_risk_type,
)

CATALOG_TARGET_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
ERROR_STATUS = {
    "SUBJECT_RISK_CONFIG_INTEGRITY_ERROR": HTTP_503_SERVICE_UNAVAILABLE,
    "SUBJECT_RISK_CATALOG_VERSION_CONFLICT": HTTP_409_CONFLICT,
    "SUBJECT_RISK_TYPE_VERSION_CONFLICT": HTTP_409_CONFLICT,
    "SUBJECT_RISK_RULE_VERSION_CONFLICT": HTTP_409_CONFLICT,
    "SUBJECT_REVIEW_STATE_CONFLICT": HTTP_409_CONFLICT,
    "SUBJECT_REVIEW_VERSION_CONFLICT": HTTP_409_CONFLICT,
    "SUBJECT_REVIEW_REASON_REQUIRED": HTTP_422_UNPROCESSABLE_ENTITY,
}


def _risk_error(exc, request):
    return error_response(ErrorCode(exc.code), status_code=ERROR_STATUS[exc.code], request=request)


def _pagination(request):
    try:
        page = max(int(request.query_params.get("page", 1)), 1)
        page_size = min(max(int(request.query_params.get("page_size", 20)), 1), 100)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            {"page": ["\u5206\u9875\u53c2\u6570\u4e0d\u6b63\u786e\u3002"]}
        ) from exc
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


class AdminRiskTypeListView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "subject_risk.catalog.view"
    required_permissions_by_method = {
        "GET": "subject_risk.catalog.view",
        "POST": "subject_risk.catalog.update",
    }

    def get(self, request):
        return Response(
            {
                "catalog_version": catalog_state().version,
                "risk_types": RiskTypeSerializer(
                    SubjectRiskType.objects.order_by("sort_order", "key", "id"), many=True
                ).data,
            }
        )

    @method_decorator(csrf_protect)
    def post(self, request):
        serializer = RiskTypeCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            row = create_risk_type(request=request, data=dict(serializer.validated_data))
        except SubjectRiskError as exc:
            return _risk_error(exc, request)
        return Response(RiskTypeSerializer(row).data, status=201)


class AdminRiskTypeDetailView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "subject_risk.catalog.update"

    @method_decorator(csrf_protect)
    def patch(self, request, risk_type_id):
        serializer = RiskTypeUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            row = update_risk_type(
                request=request,
                risk_type_id=risk_type_id,
                data=dict(serializer.validated_data),
            )
        except SubjectRiskError as exc:
            return _risk_error(exc, request)
        return Response(RiskTypeSerializer(row).data)


class AdminRiskRuleListView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "subject_risk.catalog.view"
    required_permissions_by_method = {
        "GET": "subject_risk.catalog.view",
        "POST": "subject_risk.catalog.update",
    }

    def get(self, request):
        rows = SubjectRiskRule.objects.select_related("risk_type", "subject_type").order_by(
            "priority", "key", "id"
        )
        return Response(
            {
                "catalog_version": catalog_state().version,
                "rules": RiskRuleSerializer(rows, many=True).data,
            }
        )

    @method_decorator(csrf_protect)
    def post(self, request):
        serializer = RiskRuleCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            row = create_risk_rule(request=request, data=dict(serializer.validated_data))
        except SubjectRiskError as exc:
            return _risk_error(exc, request)
        return Response(RiskRuleSerializer(row).data, status=201)


class AdminRiskRuleDetailView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "subject_risk.catalog.update"

    @method_decorator(csrf_protect)
    def patch(self, request, risk_rule_id):
        serializer = RiskRuleUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            row = update_risk_rule(
                request=request,
                risk_rule_id=risk_rule_id,
                data=dict(serializer.validated_data),
            )
        except SubjectRiskError as exc:
            return _risk_error(exc, request)
        return Response(RiskRuleSerializer(row).data)


class AdminRiskCatalogView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "subject_risk.catalog.view"

    def get(self, request):
        state = catalog_state()
        return Response(
            {
                "version": state.version,
                "published_revision": (
                    CatalogRevisionSerializer(state.published_revision).data
                    if state.published_revision_id
                    else None
                ),
            }
        )


class AdminRiskCatalogPublishView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "subject_risk.catalog.publish"

    @method_decorator(csrf_protect)
    def post(self, request):
        serializer = CatalogPublishSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            draft_version, draft_digest = draft_catalog_binding(
                serializer.validated_data["expected_catalog_version"]
            )
            result = perform_risk_action(
                request=request,
                action_key="subject_risk.catalog.publish",
                target_id=CATALOG_TARGET_ID,
                target_version=draft_version,
                raw_payload={"draft_digest": draft_digest},
                confirmed=serializer.validated_data["confirmed"],
                current_password=serializer.validated_data["current_password"],
            )
        except RiskError as exc:
            return risk_error_response(exc, request)
        except SubjectRiskError as exc:
            return _risk_error(exc, request)
        return Response(
            result.data,
            status=HTTP_202_ACCEPTED if result.approval_required else 200,
        )


class AdminSubjectReviewListView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "subject_reviews.list"

    def get(self, request):
        rows = scoped_reviews(
            user=request.user, admin_context=request.admin_context
        ).select_related("subject", "subject__user", "subject_version", "assessment")
        status_value = request.query_params.get("status")
        if status_value:
            if status_value not in SubjectReview.Status.values:
                raise ValidationError(
                    {"status": ["\u5ba1\u6838\u72b6\u6001\u4e0d\u6b63\u786e\u3002"]}
                )
            rows = rows.filter(status=status_value)
        return Response(_page(rows.order_by("-created_at", "-id"), ReviewSerializer, request))


class AdminSubjectReviewDetailView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "subject_reviews.view"

    def get(self, request, review_id):
        row = scoped_review_or_404(
            user=request.user,
            admin_context=request.admin_context,
            review_id=review_id,
        )
        return Response(ReviewSerializer(row).data)


class AdminSubjectReviewDecisionView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "subject_reviews.review"
    decision = ""

    @method_decorator(csrf_protect)
    def post(self, request, review_id):
        serializer = ReviewDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            row = decide_review(
                request=request,
                review_id=review_id,
                decision=self.decision,
                **serializer.validated_data,
            )
        except SubjectRiskError as exc:
            return _risk_error(exc, request)
        return Response(ReviewSerializer(row).data)


class AdminSubjectReviewApproveView(AdminSubjectReviewDecisionView):
    decision = SubjectReview.Status.APPROVED


class AdminSubjectReviewRejectView(AdminSubjectReviewDecisionView):
    decision = SubjectReview.Status.REJECTED
