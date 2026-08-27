from __future__ import annotations

import logging

from django.db import transaction
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.response import Response
from rest_framework.status import HTTP_201_CREATED, HTTP_202_ACCEPTED
from rest_framework.views import APIView

from apps.core.error_codes import ErrorCode
from apps.core.responses import error_response
from apps.quotas.exceptions import QuotaError
from apps.subjects.permissions import IsAvailableAuthenticatedUser
from apps.subjects.subject_services import subject_for_user_or_404

from .models import Article
from .services import ContentError
from .tasks import execute_video_script_job_task
from .video_serializers import VideoScriptCreateSerializer, VideoScriptSaveSerializer
from .video_services import (
    VIDEO_SCRIPT_CUSTOM_TYPE,
    create_video_generation_job,
    create_video_script,
    save_video_script,
    video_failure,
    video_job_payload,
    video_script_for_user,
    video_script_payload,
)

logger = logging.getLogger(__name__)


def _no_store(response):
    response["Cache-Control"] = "no-store"
    return response


def _content_error(exc, request):
    return error_response(
        ErrorCode.VALIDATION_ERROR
        if exc.status == 422
        else ErrorCode.SERVICE_TEMPORARILY_UNAVAILABLE
        if exc.status == 503
        else ErrorCode.PERMISSION_DENIED
        if exc.status == 403
        else ErrorCode.IDEMPOTENCY_CONFLICT,
        status_code=exc.status,
        request=request,
        message=exc.code,
        details={"content_code": exc.code},
    )


def _quota_error(exc, request):
    return error_response(
        ErrorCode.QUOTA_INSUFFICIENT
        if exc.code == "QUOTA_INSUFFICIENT"
        else ErrorCode.QUOTA_STATE_CONFLICT,
        status_code=409,
        request=request,
        details={"quota_code": exc.code},
    )


def _enqueue_video(job):
    try:
        execute_video_script_job_task.apply_async(args=[str(job.pk)], queue="ai_content")
    except Exception:
        logger.exception(
            "video script generation enqueue failed",
            extra={"context": {"job_id": str(job.pk)}},
        )
        video_failure(job.pk, "VIDEO_SCRIPT_QUEUE_UNAVAILABLE")


class SubjectVideoScriptListCreateView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        subject = subject_for_user_or_404(user=request.user, subject_id=subject_id)
        page = max(1, int(request.query_params.get("page", "1")))
        page_size = min(50, max(1, int(request.query_params.get("page_size", "20"))))
        query = Article.objects.filter(
            subject=subject,
            user=request.user,
            custom_type=VIDEO_SCRIPT_CUSTOM_TYPE,
        ).select_related("subject", "subject_version")
        count = query.count()
        rows = query[(page - 1) * page_size : page * page_size]
        return _no_store(
            Response(
                {
                    "items": [video_script_payload(row) for row in rows],
                    "pagination": {
                        "page": page,
                        "page_size": page_size,
                        "count": count,
                        "total_pages": (count + page_size - 1) // page_size,
                    },
                }
            )
        )

    @method_decorator(csrf_protect)
    def post(self, request, subject_id):
        serializer = VideoScriptCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            article = create_video_script(
                user=request.user,
                subject_id=subject_id,
                **serializer.validated_data,
            )
        except ContentError as exc:
            return _content_error(exc, request)
        return _no_store(Response(video_script_payload(article), status=HTTP_201_CREATED))


class VideoScriptDetailView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, video_script_id):
        return _no_store(
            Response(video_script_payload(video_script_for_user(request.user, video_script_id)))
        )

    @method_decorator(csrf_protect)
    def patch(self, request, video_script_id):
        serializer = VideoScriptSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data
        script = {
            "hooks": validated["hooks"],
            "scenes": validated["scenes"],
            "full_voiceover": validated["full_voiceover"],
            "cta": validated["cta"],
        }
        try:
            article = save_video_script(
                user=request.user,
                video_script_id=video_script_id,
                title=validated["title"],
                script=script,
                expected_version=validated["expected_version"],
            )
        except ContentError as exc:
            return _content_error(exc, request)
        return _no_store(Response(video_script_payload(article)))


class VideoScriptGenerateView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, video_script_id):
        try:
            with transaction.atomic():
                job, created = create_video_generation_job(
                    user=request.user,
                    video_script_id=video_script_id,
                    idempotency_key=request.headers.get("Idempotency-Key", ""),
                    request_id=request.request_id,
                )
                if created:
                    transaction.on_commit(lambda: _enqueue_video(job))
        except ContentError as exc:
            return _content_error(exc, request)
        except QuotaError as exc:
            return _quota_error(exc, request)
        return _no_store(Response(video_job_payload(job), status=HTTP_202_ACCEPTED))


class VideoArticleOptionsView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        subject = subject_for_user_or_404(user=request.user, subject_id=subject_id)
        rows = (
            Article.objects.filter(subject=subject, user=request.user)
            .exclude(custom_type=VIDEO_SCRIPT_CUSTOM_TYPE)
            .exclude(content="")
            .order_by("-updated_at", "-id")[:100]
        )
        return _no_store(
            Response(
                {
                    "items": [
                        {
                            "id": str(row.pk),
                            "title": row.title or "未命名文章",
                            "status": row.status,
                            "updated_at": row.updated_at,
                        }
                        for row in rows
                    ]
                }
            )
        )
