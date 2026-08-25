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

from .exceptions import KeywordError
from .generation_exceptions import KeywordGenerationError
from .generation_serializers import KeywordGenerationCreateSerializer
from .generation_services import (
    create_keyword_generation_job,
    keyword_generation_job_for_user_or_404,
    keyword_generation_quota_payload,
)
from .generation_tasks import execute_keyword_generation_task

logger = logging.getLogger(__name__)

ERROR_STATUS = {
    "KEYWORD_GENERATION_STATE_CONFLICT": HTTP_409_CONFLICT,
    "KEYWORD_GENERATION_IN_PROGRESS": HTTP_409_CONFLICT,
    "KEYWORD_REGENERATION_CONFIRMATION_REQUIRED": HTTP_409_CONFLICT,
    "KEYWORD_VERSION_CONFLICT": HTTP_409_CONFLICT,
    "KEYWORD_SUBJECT_VERSION_CONFLICT": HTTP_409_CONFLICT,
    "KEYWORD_GENERATION_LIMIT_EXCEEDED": HTTP_422_UNPROCESSABLE_ENTITY,
    "KEYWORD_GENERATION_CONFIG_INVALID": HTTP_422_UNPROCESSABLE_ENTITY,
    "KEYWORD_GENERATION_IDEMPOTENCY_KEY_REQUIRED": HTTP_422_UNPROCESSABLE_ENTITY,
    "IDEMPOTENCY_CONFLICT": HTTP_409_CONFLICT,
    "KEYWORD_GENERATION_PROVIDER_UNAVAILABLE": HTTP_503_SERVICE_UNAVAILABLE,
    "KEYWORD_GENERATION_INVALID_RESPONSE": HTTP_422_UNPROCESSABLE_ENTITY,
    "KEYWORD_STATE_CONFLICT": HTTP_409_CONFLICT,
    "KEYWORD_VALUES_INVALID": HTTP_422_UNPROCESSABLE_ENTITY,
    "KEYWORD_VERSION_NO_CHANGES": HTTP_409_CONFLICT,
    "PLAN_REQUIRED": HTTP_409_CONFLICT,
    "ACCOUNT_UNAVAILABLE": HTTP_409_CONFLICT,
}
QUOTA_ERROR_STATUS = {
    "QUOTA_INSUFFICIENT": HTTP_409_CONFLICT,
    "QUOTA_STATE_CONFLICT": HTTP_409_CONFLICT,
    "QUOTA_VERSION_CONFLICT": HTTP_409_CONFLICT,
    "QUOTA_HOLD_STATE_CONFLICT": HTTP_409_CONFLICT,
    "QUOTA_BUSINESS_ALREADY_HELD": HTTP_409_CONFLICT,
    "IDEMPOTENCY_CONFLICT": HTTP_409_CONFLICT,
}


def _error(exc, request):
    return error_response(
        ErrorCode(exc.code),
        status_code=ERROR_STATUS.get(exc.code, HTTP_409_CONFLICT),
        request=request,
    )


def _quota_error(exc, request):
    code = exc.code if exc.code in QUOTA_ERROR_STATUS else "PLAN_REQUIRED"
    return error_response(
        ErrorCode(code),
        status_code=QUOTA_ERROR_STATUS.get(code, HTTP_409_CONFLICT),
        request=request,
    )


def _no_store(response):
    response["Cache-Control"] = "no-store"
    return response


def _enqueue(job_id, request_id):
    try:
        execute_keyword_generation_task.apply_async(
            args=[str(job_id)],
            queue="ai_content",
            headers={
                "request_id": str(request_id),
                "correlation_id": str(request_id),
            },
        )
    except Exception:
        logger.exception(
            "keyword generation enqueue failed",
            extra={"context": {"job_id": str(job_id)}},
        )


def _job_payload(job):
    result = getattr(job, "result", None)
    return {
        "id": str(job.pk),
        "subject_id": str(job.subject_id),
        "subject_version_id": str(job.subject_version_id),
        "status": job.status,
        "version": job.version,
        "stable_error_code": job.stable_error_code,
        "billing": keyword_generation_quota_payload(job),
        "configuration": {
            "target_count": job.target_count,
            "include_short": job.include_short,
            "include_long_tail": job.include_long_tail,
            "include_regional": job.include_regional,
            "regions": job.regions,
            "generation_mode": job.generation_mode,
            "categories": job.requested_categories,
            "intents": job.requested_intents,
            "region_mode": job.region_mode,
        },
        "provenance": {
            "provider_key": job.provider_key,
            "model_key": job.model_key,
            "adapter_version": job.adapter_version,
            "prompt_version": job.prompt_version,
        },
        "result": (
            {
                "item_count": result.item_count,
                "applied_keyword_set_version": result.applied_keyword_set_version,
            }
            if result
            else None
        ),
        "attempts": job.attempts,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "finished_at": job.finished_at,
    }


class KeywordGenerationCreateView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, subject_id):
        serializer = KeywordGenerationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                job, created = create_keyword_generation_job(
                    user_id=request.user.pk,
                    subject_id=subject_id,
                    idempotency_key=request.headers.get(
                        "Idempotency-Key",
                        "",
                    ),
                    request_id=request.request_id,
                    **serializer.validated_data,
                )
                if created:
                    transaction.on_commit(lambda: _enqueue(job.pk, request.request_id))
        except KeywordGenerationError as exc:
            return _error(exc, request)
        except KeywordError as exc:
            return _error(exc, request)
        except QuotaError as exc:
            return _quota_error(exc, request)
        return _no_store(Response(_job_payload(job), status=HTTP_202_ACCEPTED))


class KeywordGenerationDetailView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, job_id):
        job = keyword_generation_job_for_user_or_404(
            user=request.user,
            job_id=job_id,
        )
        return _no_store(Response(_job_payload(job)))
