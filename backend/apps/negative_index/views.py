from __future__ import annotations

from django.db import transaction
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_201_CREATED,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
)
from rest_framework.views import APIView

from apps.subjects.models import Subject
from apps.subjects.permissions import IsAvailableAuthenticatedUser

from .models import NegativeEvent, NegativeIndexScan
from .serializers import (
    NegativeEventDetailSerializer,
    NegativeEventSummarySerializer,
    NegativeIndexScanDetailSerializer,
    NegativeIndexScanSummarySerializer,
)
from .services import (
    NegativeIndexBusy,
    NegativeIndexNotFound,
    create_negative_index_scan,
    recover_stale_negative_index_scans,
)
from .tasks import execute_negative_index_scan_task

COMPLETED_STATUSES = (
    NegativeIndexScan.Status.SUCCEEDED,
    NegativeIndexScan.Status.PARTIAL,
    NegativeIndexScan.Status.LIMIT_REACHED,
)
ACTIVE_STATUSES = (
    NegativeIndexScan.Status.QUEUED,
    NegativeIndexScan.Status.RUNNING,
)


class NegativeIndexPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class NegativeIndexScanCreateView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def post(self, request, subject_id):
        try:
            with transaction.atomic():
                scan = create_negative_index_scan(
                    user=request.user,
                    subject_id=subject_id,
                )
                transaction.on_commit(
                    lambda: execute_negative_index_scan_task.apply_async(
                        args=[str(scan.id)],
                        queue="web_fetch",
                    )
                )
        except NegativeIndexNotFound:
            return Response(
                {"detail": "主体不存在。"},
                status=HTTP_404_NOT_FOUND,
            )
        except NegativeIndexBusy:
            return Response(
                {"detail": "当前主体已有负面信息扫描正在进行。"},
                status=HTTP_409_CONFLICT,
            )
        return Response(
            NegativeIndexScanSummarySerializer(scan).data,
            status=HTTP_201_CREATED,
        )


class SubjectNegativeIndexView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        if not Subject.objects.filter(pk=subject_id, user=request.user).exists():
            return Response(
                {"detail": "主体不存在。"},
                status=HTTP_404_NOT_FOUND,
            )

        recover_stale_negative_index_scans(
            user=request.user,
            subject_id=subject_id,
        )
        scans = NegativeIndexScan.objects.filter(
            user=request.user,
            subject_id=subject_id,
        )
        active = (
            scans.filter(status__in=ACTIVE_STATUSES)
            .order_by("-created_at")
            .first()
        )
        latest = (
            scans.filter(status__in=COMPLETED_STATUSES)
            .order_by("-finished_at", "-created_at")
            .first()
        )
        history = scans.filter(status__in=COMPLETED_STATUSES).order_by(
            "-finished_at",
            "-created_at",
        )[:30]
        return Response(
            {
                "active_scan": (
                    NegativeIndexScanSummarySerializer(active).data
                    if active
                    else None
                ),
                "latest_result": (
                    NegativeIndexScanDetailSerializer(latest).data
                    if latest
                    else None
                ),
                "history": NegativeIndexScanSummarySerializer(
                    history,
                    many=True,
                ).data,
            }
        )


class NegativeIndexScanDetailView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, scan_id):
        recover_stale_negative_index_scans(user=request.user)
        scan = NegativeIndexScan.objects.filter(
            pk=scan_id,
            user=request.user,
        ).first()
        if scan is None:
            return Response(
                {"detail": "负面信息扫描记录不存在。"},
                status=HTTP_404_NOT_FOUND,
            )
        return Response(NegativeIndexScanDetailSerializer(scan).data)


class NegativeIndexEventListView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, scan_id):
        scan = NegativeIndexScan.objects.filter(
            pk=scan_id,
            user=request.user,
        ).first()
        if scan is None:
            return Response(
                {"detail": "负面信息扫描记录不存在。"},
                status=HTTP_404_NOT_FOUND,
            )

        queryset = NegativeEvent.objects.filter(scan=scan)
        category = request.query_params.get("category", "").strip()
        status = request.query_params.get("status", "").strip()
        valid_categories = {value for value, _ in NegativeEvent.Category.choices}
        valid_statuses = {value for value, _ in NegativeEvent.Status.choices}
        if category in valid_categories:
            queryset = queryset.filter(category=category)
        if status in valid_statuses:
            queryset = queryset.filter(status=status)

        ordering = request.query_params.get("ordering", "-current_risk").strip()
        allowed_ordering = {
            "current_risk",
            "-current_risk",
            "last_seen_at",
            "-last_seen_at",
            "severity_score",
            "-severity_score",
            "evidence_score",
            "-evidence_score",
        }
        if ordering not in allowed_ordering:
            ordering = "-current_risk"
        queryset = queryset.order_by(ordering, "id")

        paginator = NegativeIndexPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = NegativeEventSummarySerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class NegativeIndexEventDetailView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, event_id):
        event = (
            NegativeEvent.objects.filter(
                pk=event_id,
                scan__user=request.user,
            )
            .select_related("scan")
            .first()
        )
        if event is None:
            return Response(
                {"detail": "负面风险事件不存在。"},
                status=HTTP_404_NOT_FOUND,
            )
        return Response(NegativeEventDetailSerializer(event).data)
