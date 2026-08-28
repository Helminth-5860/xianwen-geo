from __future__ import annotations

from django.db import transaction
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import HTTP_201_CREATED, HTTP_404_NOT_FOUND, HTTP_409_CONFLICT
from rest_framework.views import APIView

from apps.subjects.models import Subject

from .models import SourceIndexItem, SourceIndexScan
from .serializers import (
    SourceIndexItemSerializer,
    SourceIndexScanDetailSerializer,
    SourceIndexScanSummarySerializer,
)
from .services import (
    SourceIndexBusy,
    SourceIndexNotFound,
    create_source_index_scan,
    recover_stale_source_index_scans,
)
from .tasks import execute_source_index_scan_task

COMPLETED_STATUSES = (
    SourceIndexScan.Status.SUCCEEDED,
    SourceIndexScan.Status.PARTIAL,
    SourceIndexScan.Status.LIMIT_REACHED,
)
ACTIVE_STATUSES = (SourceIndexScan.Status.QUEUED, SourceIndexScan.Status.RUNNING)


class SourceIndexPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 100


class SourceIndexScanCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, subject_id):
        try:
            with transaction.atomic():
                scan = create_source_index_scan(user=request.user, subject_id=subject_id)
                transaction.on_commit(
                    lambda: execute_source_index_scan_task.apply_async(
                        args=[str(scan.id)],
                        queue="web_fetch",
                    )
                )
        except SourceIndexNotFound:
            return Response({"detail": "主体不存在。"}, status=HTTP_404_NOT_FOUND)
        except SourceIndexBusy:
            return Response(
                {"detail": "当前主体已有信源扫描正在进行。"},
                status=HTTP_409_CONFLICT,
            )
        return Response(SourceIndexScanSummarySerializer(scan).data, status=HTTP_201_CREATED)


class SubjectSourceIndexView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, subject_id):
        if not Subject.objects.filter(pk=subject_id, user=request.user).exists():
            return Response({"detail": "主体不存在。"}, status=HTTP_404_NOT_FOUND)
        recover_stale_source_index_scans(user=request.user, subject_id=subject_id)
        scans = SourceIndexScan.objects.filter(user=request.user, subject_id=subject_id)
        active = scans.filter(status__in=ACTIVE_STATUSES).order_by("-created_at").first()
        latest = (
            scans.filter(status__in=COMPLETED_STATUSES)
            .order_by("-finished_at", "-created_at")
            .first()
        )
        return Response(
            {
                "active_scan": SourceIndexScanSummarySerializer(active).data if active else None,
                "latest_result": SourceIndexScanDetailSerializer(latest).data if latest else None,
            }
        )


class SourceIndexScanDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, scan_id):
        recover_stale_source_index_scans(user=request.user)
        scan = SourceIndexScan.objects.filter(pk=scan_id, user=request.user).first()
        if scan is None:
            return Response({"detail": "信源扫描记录不存在。"}, status=HTTP_404_NOT_FOUND)
        return Response(SourceIndexScanDetailSerializer(scan).data)


class SourceIndexSourceListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, scan_id):
        scan = SourceIndexScan.objects.filter(pk=scan_id, user=request.user).first()
        if scan is None:
            return Response({"detail": "信源扫描记录不存在。"}, status=HTTP_404_NOT_FOUND)
        queryset = SourceIndexItem.objects.filter(scan=scan).prefetch_related("hits")
        source_type = request.query_params.get("source_type", "").strip()
        if source_type:
            valid_types = {choice for choice, _label in SourceIndexItem.SourceType.choices}
            if source_type in valid_types:
                queryset = queryset.filter(source_type=source_type)
        ordering = request.query_params.get("ordering", "-source_weight").strip()
        allowed_ordering = {
            "source_weight",
            "-source_weight",
            "published_at",
            "-published_at",
            "best_rank",
            "-best_rank",
            "authority_score",
            "-authority_score",
        }
        if ordering not in allowed_ordering:
            ordering = "-source_weight"
        queryset = queryset.order_by(ordering, "id")
        paginator = SourceIndexPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = SourceIndexItemSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)
