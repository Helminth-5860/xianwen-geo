from __future__ import annotations

import logging
import math
import uuid

from django.db import transaction
from django.http import FileResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.response import Response
from rest_framework.status import HTTP_202_ACCEPTED
from rest_framework.views import APIView

from apps.core.error_codes import ErrorCode
from apps.core.responses import error_response
from apps.documents.exceptions import FileStorageUnavailable
from apps.documents.storage import storage_provider
from apps.quotas.exceptions import QuotaError
from apps.subjects.permissions import IsAvailableAuthenticatedUser

from .exceptions import VideoBusinessError, VideoServiceUnavailable
from .models import VideoAsset, VideoGenerationJob
from .serializers import (
    EmptyVideoActionSerializer,
    ExpectedVideoVersionSerializer,
    VideoJobCreateSerializer,
)
from .services import (
    _subject,
    create_download_intent,
    create_video_job,
    job_payload,
    quota_summary,
    regenerate_video_job,
    save_to_library,
    terminal_failure,
    video_asset_for_user,
    video_job_for_user,
    video_payload,
)
from .tasks import execute_video_job_task

logger = logging.getLogger(__name__)


def _no_store(response):
    response["Cache-Control"] = "no-store"
    return response


def _video_error(exc: VideoBusinessError, request):
    core_code = (
        ErrorCode.VALIDATION_ERROR
        if exc.status == 422
        else ErrorCode.SERVICE_TEMPORARILY_UNAVAILABLE
        if exc.status == 503
        else ErrorCode.IDEMPOTENCY_CONFLICT
        if exc.code == "VIDEO_IDEMPOTENCY_CONFLICT"
        else ErrorCode.ACCOUNT_STATE_CONFLICT
    )
    return _no_store(
        error_response(
            core_code,
            status_code=exc.status,
            request=request,
            message=exc.message,
            details={"video_code": exc.code},
        )
    )


def _quota_error(exc: QuotaError, request):
    return _no_store(
        error_response(
            ErrorCode.QUOTA_INSUFFICIENT
            if exc.code == "QUOTA_INSUFFICIENT"
            else ErrorCode.QUOTA_STATE_CONFLICT,
            status_code=409,
            request=request,
            message=(
                "视频生成额度不足，请调整时长或升级套餐。"
                if exc.code == "QUOTA_INSUFFICIENT"
                else "当前额度状态已发生变化，请刷新后重试。"
            ),
            details={
                "video_code": (
                    "VIDEO_QUOTA_INSUFFICIENT"
                    if exc.code == "QUOTA_INSUFFICIENT"
                    else "VIDEO_QUOTA_STATE_CONFLICT"
                )
            },
        )
    )


def _enqueue(job: VideoGenerationJob) -> None:
    try:
        execute_video_job_task.apply_async(args=[str(job.pk)], queue="image_generation")
    except Exception as exc:
        logger.error(
            "video generation enqueue failed",
            extra={"job_id": str(job.pk), "exception_type": type(exc).__name__},
        )
        terminal_failure(
            job.pk,
            "VIDEO_QUEUE_UNAVAILABLE",
            "视频任务暂时无法启动，请稍后重新生成。",
        )


def _page_values(request) -> tuple[int, int]:
    try:
        page = int(request.query_params.get("page", "1"))
        page_size = int(request.query_params.get("page_size", "20"))
    except (TypeError, ValueError) as exc:
        raise VideoBusinessError("VIDEO_PAGE_INVALID", "分页参数不正确。", status=422) from exc
    if page < 1 or page_size < 1 or page_size > 20:
        raise VideoBusinessError("VIDEO_PAGE_INVALID", "每页最多显示 20 条记录。", status=422)
    return page, page_size


def _pagination(*, page: int, page_size: int, count: int) -> dict[str, int]:
    return {
        "page": page,
        "page_size": page_size,
        "count": count,
        "total_pages": max(1, math.ceil(count / page_size)),
    }


class SubjectVideoJobsView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        subject = _subject(request.user, subject_id)
        try:
            page, page_size = _page_values(request)
        except VideoBusinessError as exc:
            return _video_error(exc, request)
        rows = VideoGenerationJob.objects.filter(
            user=request.user,
            tenant_id=request.user.tenant_id,
            subject=subject,
            subject__user=request.user,
        ).select_related("result_asset", "quota_hold")
        count = rows.count()
        start = (page - 1) * page_size
        items = list(rows[start : start + page_size])
        return _no_store(
            Response(
                {
                    "items": [job_payload(row) for row in items],
                    "pagination": _pagination(page=page, page_size=page_size, count=count),
                    "quota": quota_summary(request.user),
                }
            )
        )

    @method_decorator(csrf_protect)
    def post(self, request, subject_id):
        serializer = VideoJobCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                job, created = create_video_job(
                    user=request.user,
                    subject_id=subject_id,
                    idempotency_key=request.headers.get("Idempotency-Key", ""),
                    request_id=uuid.UUID(str(request.request_id)),
                    **serializer.validated_data,
                )
                if created:
                    transaction.on_commit(lambda: _enqueue(job))
        except VideoBusinessError as exc:
            return _video_error(exc, request)
        except QuotaError as exc:
            return _quota_error(exc, request)
        job = video_job_for_user(user=request.user, job_id=job.pk)
        return _no_store(
            Response(
                {"job": job_payload(job), "quota": quota_summary(request.user)},
                status=HTTP_202_ACCEPTED,
            )
        )


class VideoJobView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, job_id):
        job = video_job_for_user(user=request.user, job_id=job_id)
        return _no_store(Response(job_payload(job)))


class VideoJobRegenerateView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, job_id):
        serializer = EmptyVideoActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                job, created = regenerate_video_job(
                    user=request.user,
                    job_id=job_id,
                    idempotency_key=request.headers.get("Idempotency-Key", ""),
                    request_id=uuid.UUID(str(request.request_id)),
                )
                if created:
                    transaction.on_commit(lambda: _enqueue(job))
        except VideoBusinessError as exc:
            return _video_error(exc, request)
        except QuotaError as exc:
            return _quota_error(exc, request)
        job = video_job_for_user(user=request.user, job_id=job.pk)
        return _no_store(
            Response(
                {"job": job_payload(job), "quota": quota_summary(request.user)},
                status=HTTP_202_ACCEPTED,
            )
        )


class VideoJobDownloadIntentView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, job_id):
        serializer = EmptyVideoActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            payload = create_download_intent(user=request.user, job_id=job_id)
        except VideoBusinessError as exc:
            return _video_error(exc, request)
        return _no_store(Response(payload))


class VideoJobSaveLibraryView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, job_id):
        serializer = ExpectedVideoVersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            video = save_to_library(
                user=request.user,
                job_id=job_id,
                expected_version=serializer.validated_data["expected_version"],
            )
        except VideoBusinessError as exc:
            return _video_error(exc, request)
        return _no_store(Response(video_payload(video)))


class SubjectVideosView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        subject = _subject(request.user, subject_id)
        try:
            page, page_size = _page_values(request)
        except VideoBusinessError as exc:
            return _video_error(exc, request)
        rows = VideoAsset.objects.filter(
            user=request.user,
            tenant_id=request.user.tenant_id,
            subject=subject,
            subject__user=request.user,
            generation_job__user=request.user,
            generation_job__tenant_id=request.user.tenant_id,
            generation_job__status=VideoGenerationJob.Status.SUCCEEDED,
        ).select_related("generation_job")
        if request.query_params.get("library") == "true":
            rows = rows.filter(is_subject_library=True)
        count = rows.count()
        start = (page - 1) * page_size
        items = list(rows[start : start + page_size])
        return _no_store(
            Response(
                {
                    "items": [video_payload(row) for row in items],
                    "pagination": _pagination(page=page, page_size=page_size, count=count),
                }
            )
        )


class VideoContentView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id, video_id):
        _subject(request.user, subject_id)
        video = video_asset_for_user(
            user=request.user,
            video_id=video_id,
            subject_id=subject_id,
        )
        try:
            source = storage_provider().open_object(video.object_key)
        except FileStorageUnavailable:
            return _video_error(
                VideoServiceUnavailable("VIDEO_STORAGE_FAILED", "视频暂时无法播放，请稍后重试。"),
                request,
            )
        response = FileResponse(
            source,
            as_attachment=False,
            filename=f"video-{video.pk}.mp4",
            content_type=video.mime_type,
        )
        response["Content-Length"] = str(video.size_bytes)
        response["Accept-Ranges"] = "none"
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "default-src 'none'; media-src 'self'"
        return response
