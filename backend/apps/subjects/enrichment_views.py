import logging

from django.db import transaction
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_202_ACCEPTED,
    HTTP_409_CONFLICT,
    HTTP_422_UNPROCESSABLE_ENTITY,
    HTTP_429_TOO_MANY_REQUESTS,
    HTTP_503_SERVICE_UNAVAILABLE,
)
from rest_framework.views import APIView

from apps.core.error_codes import ErrorCode
from apps.core.responses import error_response

from .enrichment_exceptions import SubjectEnrichmentError
from .enrichment_serializers import (
    SubjectEnrichmentConfirmSerializer,
    SubjectEnrichmentCreateSerializer,
)
from .enrichment_services import (
    available_sources,
    available_targets,
    confirm_enrichment,
    create_enrichment_job,
    enrichment_job_for_user_or_404,
    latest_unapplied_job,
)
from .enrichment_tasks import execute_enrichment_task
from .models import SubjectEnrichmentJob
from .permissions import IsAvailableAuthenticatedUser
from .serializers import SubjectDetailSerializer
from .subject_services import subject_for_user_or_404

logger = logging.getLogger(__name__)

ERROR_STATUS = {
    "SUBJECT_ENRICHMENT_STATE_CONFLICT": HTTP_409_CONFLICT,
    "SUBJECT_ENRICHMENT_VERSION_CONFLICT": HTTP_409_CONFLICT,
    "SUBJECT_ENRICHMENT_IDEMPOTENCY_KEY_REQUIRED": HTTP_422_UNPROCESSABLE_ENTITY,
    "IDEMPOTENCY_CONFLICT": HTTP_409_CONFLICT,
    "SUBJECT_ENRICHMENT_SOURCE_INVALID": HTTP_422_UNPROCESSABLE_ENTITY,
    "SUBJECT_ENRICHMENT_TARGET_INVALID": HTTP_422_UNPROCESSABLE_ENTITY,
    "SUBJECT_ENRICHMENT_INPUT_TOO_LARGE": HTTP_422_UNPROCESSABLE_ENTITY,
    "SUBJECT_ENRICHMENT_INVALID_RESPONSE": HTTP_422_UNPROCESSABLE_ENTITY,
    "SUBJECT_ENRICHMENT_PROVIDER_UNAVAILABLE": HTTP_503_SERVICE_UNAVAILABLE,
    "SUBJECT_ENRICHMENT_TEMPORARILY_UNAVAILABLE": HTTP_503_SERVICE_UNAVAILABLE,
    "RATE_LIMITED": HTTP_429_TOO_MANY_REQUESTS,
}


def _error(exc, request):
    return error_response(
        ErrorCode(exc.code),
        status_code=ERROR_STATUS.get(exc.code, HTTP_409_CONFLICT),
        request=request,
    )


def _no_store(response):
    response["Cache-Control"] = "no-store"
    return response


def _enqueue(job_id, request_id):
    try:
        execute_enrichment_task.apply_async(
            args=[str(job_id)],
            queue="ai_content",
            headers={"request_id": str(request_id), "correlation_id": str(request_id)},
        )
    except Exception:
        logger.exception(
            "subject enrichment enqueue failed", extra={"context": {"job_id": str(job_id)}}
        )


def _job_payload(job: SubjectEnrichmentJob):
    suggestions = []
    for item in job.suggestions.prefetch_related("source_links__source").all():
        suggestions.append(
            {
                "id": str(item.pk),
                "field_key": item.field_key,
                "suggested_value": item.suggested_value,
                "confidence": item.confidence,
                "conflict": item.conflict,
                "conflict_code": item.conflict_code,
                "sources": [
                    {"source_id": str(link.source_id), "source_type": link.source.source_type}
                    for link in item.source_links.all()
                ],
            }
        )
    return {
        "id": str(job.pk),
        "subject_id": str(job.subject_id),
        "status": job.status,
        "version": job.version,
        "stable_error_code": job.stable_error_code,
        "provider_key": job.provider_key,
        "model_key": job.model_key,
        "suggestions": suggestions,
        "applied": hasattr(job, "confirmation"),
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


class SubjectEnrichmentSourcesView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        subject = subject_for_user_or_404(user=request.user, subject_id=subject_id)
        latest = latest_unapplied_job(user=request.user, subject=subject)
        return _no_store(
            Response(
                {
                    "sources": available_sources(user=request.user, subject=subject),
                    "target_fields": available_targets(subject),
                    "latest_job": _job_payload(latest) if latest else None,
                }
            )
        )


class SubjectEnrichmentCreateView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, subject_id):
        serializer = SubjectEnrichmentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                job, created = create_enrichment_job(
                    request=request,
                    user_id=request.user.pk,
                    subject_id=subject_id,
                    expected_subject_version=serializer.validated_data["expected_subject_version"],
                    source_refs=serializer.validated_data["sources"],
                    target_field_keys=serializer.validated_data["target_field_keys"],
                    idempotency_key=request.headers.get("Idempotency-Key", ""),
                    request_id=request.request_id,
                )
                if created:
                    transaction.on_commit(lambda: _enqueue(job.pk, request.request_id))
        except SubjectEnrichmentError as exc:
            return _error(exc, request)
        return _no_store(Response(_job_payload(job), status=HTTP_202_ACCEPTED))


class SubjectEnrichmentDetailView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id, job_id):
        job = enrichment_job_for_user_or_404(
            user=request.user, subject_id=subject_id, job_id=job_id
        )
        return _no_store(Response(_job_payload(job)))


class SubjectEnrichmentConfirmView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, subject_id, job_id):
        serializer = SubjectEnrichmentConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            subject, confirmation, created = confirm_enrichment(
                user_id=request.user.pk,
                subject_id=subject_id,
                job_id=job_id,
                expected_subject_version=serializer.validated_data["expected_subject_version"],
                expected_job_version=serializer.validated_data["expected_job_version"],
                decisions=serializer.validated_data["decisions"],
                request_id=request.request_id,
            )
        except SubjectEnrichmentError as exc:
            return _error(exc, request)
        return _no_store(
            Response(
                {
                    "created": created,
                    "confirmation_id": str(confirmation.pk),
                    "subject": SubjectDetailSerializer(subject).data,
                }
            )
        )
