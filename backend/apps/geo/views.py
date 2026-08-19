from __future__ import annotations

import logging

from django.db import transaction
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_202_ACCEPTED,
    HTTP_409_CONFLICT,
    HTTP_422_UNPROCESSABLE_ENTITY,
    HTTP_503_SERVICE_UNAVAILABLE,
)
from rest_framework.views import APIView

from apps.core.error_codes import ErrorCode
from apps.core.responses import error_response
from apps.quotas.exceptions import QuotaError
from apps.subjects.permissions import IsAvailableAuthenticatedUser

from .exceptions import GeoDetectionError
from .serializers import GeoDetectionSelectionSerializer
from .services import (
    cancel_detection,
    create_detection_job,
    detection_for_user_or_404,
    detection_history,
    detection_options,
    estimate_detection,
    job_payload,
    model_progress_payload,
    models_for_user,
)
from .tasks import dispatch_model_calls_task

logger = logging.getLogger(__name__)

ERROR_STATUS = {
    "GEO_DETECTION_VALUES_INVALID": HTTP_422_UNPROCESSABLE_ENTITY,
    "GEO_DETECTION_INPUT_CONFLICT": HTTP_409_CONFLICT,
    "GEO_DETECTION_IDEMPOTENCY_CONFLICT": HTTP_409_CONFLICT,
    "GEO_DETECTION_CONCURRENCY_LIMIT": HTTP_409_CONFLICT,
    "GEO_DETECTION_STATE_CONFLICT": HTTP_409_CONFLICT,
    "GEO_DETECTION_PROVIDER_UNAVAILABLE": HTTP_503_SERVICE_UNAVAILABLE,
}
QUOTA_ERROR_STATUS = {
    "QUOTA_INSUFFICIENT": HTTP_409_CONFLICT,
    "QUOTA_STATE_CONFLICT": HTTP_409_CONFLICT,
    "QUOTA_VERSION_CONFLICT": HTTP_409_CONFLICT,
    "QUOTA_HOLD_STATE_CONFLICT": HTTP_409_CONFLICT,
    "QUOTA_BUSINESS_ALREADY_HELD": HTTP_409_CONFLICT,
    "IDEMPOTENCY_CONFLICT": HTTP_409_CONFLICT,
}


def _no_store(response):
    response["Cache-Control"] = "no-store"
    return response


def _error(exc: GeoDetectionError, request):
    return error_response(
        ErrorCode(exc.code),
        status_code=ERROR_STATUS.get(exc.code, HTTP_409_CONFLICT),
        request=request,
    )


def _quota_error(exc: QuotaError, request):
    code = exc.code if exc.code in QUOTA_ERROR_STATUS else "PLAN_REQUIRED"
    return error_response(
        ErrorCode(code),
        status_code=QUOTA_ERROR_STATUS.get(code, HTTP_409_CONFLICT),
        request=request,
    )


def _dispatch_after_commit():
    try:
        dispatch_model_calls_task.apply_async(queue="system_tasks")
    except Exception:
        logger.exception("geo detection dispatcher enqueue failed")


class GeoModelsView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request):
        try:
            data = models_for_user(user=request.user)
        except GeoDetectionError as exc:
            return _error(exc, request)
        return _no_store(Response(data))


class GeoDetectionOptionsView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        try:
            data = detection_options(user=request.user, subject_id=subject_id)
        except GeoDetectionError as exc:
            return _error(exc, request)
        return _no_store(Response(data))


class GeoDetectionEstimateView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, subject_id):
        serializer = GeoDetectionSelectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            data = estimate_detection(
                user=request.user,
                subject_id=subject_id,
                **serializer.validated_data,
            )
        except GeoDetectionError as exc:
            return _error(exc, request)
        return _no_store(Response(data))


class GeoDetectionCreateView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        rows = detection_history(user=request.user, subject_id=subject_id)
        return _no_store(Response({"items": [job_payload(row) for row in rows]}))

    @method_decorator(csrf_protect)
    def post(self, request, subject_id):
        serializer = GeoDetectionSelectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                job, created = create_detection_job(
                    user_id=request.user.pk,
                    subject_id=subject_id,
                    idempotency_key=request.headers.get("Idempotency-Key", ""),
                    request_id=request.request_id,
                    **serializer.validated_data,
                )
                if created:
                    transaction.on_commit(_dispatch_after_commit)
        except GeoDetectionError as exc:
            return _error(exc, request)
        except QuotaError as exc:
            return _quota_error(exc, request)
        payload = {
            "detection_id": str(job.pk),
            "status": job.status,
            "planned_detection_points": job.planned_detection_points,
            "quota_hold": job.planned_detection_points,
            "status_url": f"/api/v1/geo/detections/{job.pk}",
            "replayed": not created,
        }
        return _no_store(Response(payload, status=HTTP_202_ACCEPTED))


class GeoDetectionDetailView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, detection_id):
        job = detection_for_user_or_404(user=request.user, detection_id=detection_id)
        return _no_store(Response(job_payload(job)))


class GeoDetectionModelProgressView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, detection_id):
        job = detection_for_user_or_404(user=request.user, detection_id=detection_id)
        return _no_store(Response({"items": model_progress_payload(job)}))


class GeoDetectionCancelView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, detection_id):
        try:
            job = cancel_detection(user=request.user, detection_id=detection_id)
        except GeoDetectionError as exc:
            return _error(exc, request)
        return _no_store(Response(job_payload(job)))
