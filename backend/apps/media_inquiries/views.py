from __future__ import annotations

import math

from django.db.models import Q
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_201_CREATED
from rest_framework.views import APIView

from apps.admin_rbac.permissions import HasAdminSession
from apps.core.error_codes import ErrorCode
from apps.core.responses import error_response
from apps.subjects.permissions import IsAvailableAuthenticatedUser

from .catalog import search_paid_media_catalog
from .exceptions import PaidMediaBusinessError, PaidMediaInputInvalid
from .models import PaidMediaInquiry
from .serializers import (
    PaidMediaInquiryAdminSerializer,
    PaidMediaInquiryAdminUpdateSerializer,
    PaidMediaInquiryCreateSerializer,
    PaidMediaInquirySerializer,
)
from .services import (
    admin_inquiry_or_404,
    cancel_inquiry,
    create_inquiry,
    scoped_admin_inquiries,
    subject_for_user,
    update_inquiry_status,
)


def _no_store(response):
    response["Cache-Control"] = "no-store"
    return response


def _paid_media_error(exc: PaidMediaBusinessError, request):
    core_code = (
        ErrorCode.VALIDATION_ERROR
        if exc.status == 422
        else ErrorCode.SERVICE_TEMPORARILY_UNAVAILABLE
        if exc.status == 503
        else ErrorCode.IDEMPOTENCY_CONFLICT
        if exc.code == "PAID_MEDIA_IDEMPOTENCY_CONFLICT"
        else ErrorCode.ACCOUNT_STATE_CONFLICT
    )
    return _no_store(
        error_response(
            core_code,
            status_code=exc.status,
            request=request,
            message=exc.message,
            details={"paid_media_code": exc.code},
        )
    )


def _page_values(request) -> tuple[int, int]:
    try:
        page = int(request.query_params.get("page", "1"))
        page_size = int(request.query_params.get("page_size", "20"))
    except (TypeError, ValueError) as exc:
        raise PaidMediaInputInvalid("PAID_MEDIA_PAGE_INVALID", "分页参数不正确。") from exc
    if page < 1 or page_size < 1 or page_size > 20:
        raise PaidMediaInputInvalid("PAID_MEDIA_PAGE_INVALID", "每页最多显示 20 条记录。")
    return page, page_size


def _pagination(*, page: int, page_size: int, count: int) -> dict[str, int]:
    return {
        "page": page,
        "page_size": page_size,
        "count": count,
        "total_pages": math.ceil(count / page_size) if count else 0,
    }


def _page(queryset, serializer_class, *, page: int, page_size: int):
    count = queryset.count()
    start = (page - 1) * page_size
    rows = queryset[start : start + page_size]
    return {
        "items": serializer_class(rows, many=True).data,
        "pagination": _pagination(page=page, page_size=page_size, count=count),
    }


class PaidMediaCatalogView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request):
        try:
            page, page_size = _page_values(request)
            rows = search_paid_media_catalog(request.query_params.get("search", ""))
        except PaidMediaBusinessError as exc:
            return _paid_media_error(exc, request)
        count = len(rows)
        start = (page - 1) * page_size
        return _no_store(
            Response(
                {
                    "items": [row.public_payload() for row in rows[start : start + page_size]],
                    "pagination": _pagination(page=page, page_size=page_size, count=count),
                }
            )
        )


class SubjectPaidMediaInquiryListCreateView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        subject = subject_for_user(request.user, subject_id)
        try:
            page, page_size = _page_values(request)
        except PaidMediaBusinessError as exc:
            return _paid_media_error(exc, request)
        rows = PaidMediaInquiry.objects.filter(
            user=request.user,
            tenant_id=request.user.tenant_id,
            subject=subject,
            subject__user=request.user,
            subject__user__tenant_id=request.user.tenant_id,
        ).select_related("subject", "subject__current_version")
        return _no_store(
            Response(
                _page(
                    rows,
                    PaidMediaInquirySerializer,
                    page=page,
                    page_size=page_size,
                )
            )
        )

    @method_decorator(csrf_protect)
    def post(self, request, subject_id):
        serializer = PaidMediaInquiryCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = create_inquiry(
                user=request.user,
                subject_id=subject_id,
                media_ids=serializer.validated_data["media_ids"],
                idempotency_key=request.headers.get("Idempotency-Key"),
                request_id=request.request_id,
            )
        except PaidMediaBusinessError as exc:
            return _paid_media_error(exc, request)
        inquiry = PaidMediaInquiry.objects.select_related(
            "subject", "subject__current_version"
        ).get(pk=result.inquiry.pk)
        return _no_store(
            Response(
                {"inquiry": PaidMediaInquirySerializer(inquiry).data},
                status=HTTP_200_OK if result.replayed else HTTP_201_CREATED,
            )
        )


class PaidMediaInquiryCancelView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def delete(self, request, inquiry_id, subject_id=None):
        try:
            inquiry = cancel_inquiry(
                user=request.user,
                inquiry_id=inquiry_id,
                subject_id=subject_id,
            )
        except PaidMediaBusinessError as exc:
            return _paid_media_error(exc, request)
        return _no_store(Response(PaidMediaInquirySerializer(inquiry).data))


class AdminPaidMediaInquiryListView(APIView):
    permission_classes = [HasAdminSession]

    def get(self, request):
        try:
            page, page_size = _page_values(request)
        except PaidMediaBusinessError as exc:
            return _paid_media_error(exc, request)
        rows = scoped_admin_inquiries(request.user, request.admin_context)
        status_value = request.query_params.get("status", "").strip()
        if status_value:
            if status_value not in PaidMediaInquiry.Status.values:
                return _paid_media_error(
                    PaidMediaInputInvalid("PAID_MEDIA_STATUS_INVALID", "申请状态不正确。"),
                    request,
                )
            rows = rows.filter(status=status_value)
        search = request.query_params.get("search", "").strip()
        if len(search) > 100:
            return _paid_media_error(
                PaidMediaInputInvalid(
                    "PAID_MEDIA_SEARCH_TOO_LONG", "搜索内容最多可填写 100 个字。"
                ),
                request,
            )
        if search:
            rows = rows.filter(
                Q(user__nickname__icontains=search)
                | Q(user__phone__icontains=search)
                | Q(subject__current_version__official_name__icontains=search)
            )
        return _no_store(
            Response(
                _page(
                    rows,
                    PaidMediaInquiryAdminSerializer,
                    page=page,
                    page_size=page_size,
                )
            )
        )


class AdminPaidMediaInquiryDetailView(APIView):
    permission_classes = [HasAdminSession]

    def get(self, request, inquiry_id):
        inquiry = admin_inquiry_or_404(request.user, request.admin_context, inquiry_id)
        return _no_store(Response(PaidMediaInquiryAdminSerializer(inquiry).data))

    @method_decorator(csrf_protect)
    def patch(self, request, inquiry_id):
        serializer = PaidMediaInquiryAdminUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            inquiry = update_inquiry_status(
                user=request.user,
                admin_context=request.admin_context,
                inquiry_id=inquiry_id,
                status=serializer.validated_data["status"],
                expected_version=serializer.validated_data["expected_version"],
            )
        except PaidMediaBusinessError as exc:
            return _paid_media_error(exc, request)
        return _no_store(Response(PaidMediaInquiryAdminSerializer(inquiry).data))
