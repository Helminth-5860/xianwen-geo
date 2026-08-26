import logging

from django.db import transaction
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_201_CREATED,
    HTTP_202_ACCEPTED,
    HTTP_403_FORBIDDEN,
    HTTP_409_CONFLICT,
    HTTP_422_UNPROCESSABLE_ENTITY,
    HTTP_503_SERVICE_UNAVAILABLE,
)
from rest_framework.views import APIView

from apps.core.error_codes import ErrorCode
from apps.core.responses import error_response
from apps.quotas.exceptions import QuotaError
from apps.subjects.permissions import IsAvailableAuthenticatedUser
from apps.subjects.subject_services import subject_for_user_or_404

from .distillation_exceptions import DistillationError
from .distillation_serializers import (
    DistillationConfirmSerializer,
    DistillationCreateSerializer,
    DistillationDraftSaveSerializer,
)
from .distillation_services import (
    confirm_distillation,
    create_distillation_job,
    current_distillation_for_user_or_404,
    distillation_draft_content_digest,
    distillation_job_for_user_or_404,
    distillation_quota_payload,
    distillation_workspace_for_subject,
    save_distillation_draft,
)
from .distillation_tasks import execute_distillation_task
from .exceptions import KeywordError
from .services import keyword_write_state

logger = logging.getLogger(__name__)

ERROR_STATUS = {
    "DISTILLATION_STATE_CONFLICT": HTTP_409_CONFLICT,
    "DISTILLATION_IN_PROGRESS": HTTP_409_CONFLICT,
    "DISTILLATION_REGENERATION_CONFIRMATION_REQUIRED": HTTP_409_CONFLICT,
    "DISTILLATION_VERSION_CONFLICT": HTTP_409_CONFLICT,
    "DISTILLATION_KEYWORD_VERSION_CONFLICT": HTTP_409_CONFLICT,
    "DISTILLATION_VALUES_INVALID": HTTP_422_UNPROCESSABLE_ENTITY,
    "DISTILLATION_VERSION_NO_CHANGES": HTTP_409_CONFLICT,
    "DISTILLATION_IDEMPOTENCY_KEY_REQUIRED": HTTP_422_UNPROCESSABLE_ENTITY,
    "IDEMPOTENCY_CONFLICT": HTTP_409_CONFLICT,
    "DISTILLATION_PROVIDER_UNAVAILABLE": HTTP_503_SERVICE_UNAVAILABLE,
    "DISTILLATION_INVALID_RESPONSE": HTTP_422_UNPROCESSABLE_ENTITY,
    "PLAN_REQUIRED": HTTP_403_FORBIDDEN,
    "ACCOUNT_UNAVAILABLE": HTTP_403_FORBIDDEN,
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
        execute_distillation_task.apply_async(
            args=[str(job_id)],
            queue="ai_content",
            headers={"request_id": str(request_id), "correlation_id": str(request_id)},
        )
    except Exception:
        logger.exception(
            "keyword distillation enqueue failed",
            extra={"context": {"job_id": str(job_id)}},
        )


def _job_payload(job):
    result = getattr(job, "result", None)
    return {
        "id": str(job.pk),
        "subject_id": str(job.subject_id),
        "subject_version_id": str(job.subject_version_id),
        "keyword_set_version_id": str(job.input_keyword_set_version_id),
        "status": job.status,
        "version": job.version,
        "stable_error_code": job.stable_error_code,
        "billing": distillation_quota_payload(job),
        "provenance": {
            "provider_key": job.provider_key,
            "model_key": job.model_key,
            "adapter_version": job.adapter_version,
            "prompt_version": job.prompt_version,
        },
        "result": (
            {
                "item_count": result.item_count,
                "applied_workspace_version": result.applied_workspace_version,
            }
            if result
            else None
        ),
        "attempts": job.attempts,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "finished_at": job.finished_at,
    }


def _keyword_payload(keyword):
    return {
        "id": str(keyword.pk),
        "text": keyword.text,
        "structure_type": keyword.structure_type,
        "is_regional": keyword.is_regional,
        "region_level": keyword.region_level or None,
        "region_text": keyword.region_text or None,
        "sort_order": keyword.sort_order,
    }


def _item_payload(item):
    return {
        "source_keyword": _keyword_payload(item.source_keyword),
        "action": item.action,
        "canonical_keyword_id": (
            str(item.canonical_keyword_id) if item.canonical_keyword_id else None
        ),
        "merge_group_key": str(item.merge_group_key) if item.merge_group_key else None,
        "ai_action": item.ai_action,
        "ai_canonical_keyword_id": (
            str(item.ai_canonical_keyword_id) if item.ai_canonical_keyword_id else None
        ),
        "ai_merge_group_key": (str(item.ai_merge_group_key) if item.ai_merge_group_key else None),
        "ai_reason": item.ai_reason,
        "user_reason": item.user_reason,
        "user_overridden": item.user_overridden,
        "sort_order": item.sort_order,
    }


def _workspace_payload(*, user, subject, workspace=None):
    workspace = workspace or distillation_workspace_for_subject(user=user, subject=subject)
    state = keyword_write_state(user=user, subject=subject)
    keyword_set = getattr(subject, "keyword_set", None)
    current_keyword_version = getattr(keyword_set, "current_version", None)
    current_keyword_rows = (
        list(current_keyword_version.keywords.order_by("sort_order", "id"))
        if current_keyword_version
        else []
    )
    consumed_keys = set()
    if workspace and workspace.current_set_id:
        consumed_keys = {
            (
                item.source_keyword.matching_text,
                item.source_keyword.region_matching_key,
            )
            for item in workspace.current_set.items.select_related("source_keyword")
        }
    pending_rows = [
        row
        for row in current_keyword_rows
        if (row.matching_text, row.region_matching_key) not in consumed_keys
    ]
    draft_rows = (
        list(
            workspace.draft_items.select_related(
                "source_keyword", "canonical_keyword", "ai_canonical_keyword"
            ).order_by("sort_order", "id")
        )
        if workspace
        else []
    )
    has_unconfirmed_result = bool(
        workspace
        and draft_rows
        and (
            workspace.current_set_id is None
            or workspace.current_set.input_keyword_set_version_id
            != workspace.draft_input_version_id
            or workspace.current_set.content_digest
            != distillation_draft_content_digest(workspace, rows=draft_rows)
        )
    )
    return {
        "version": workspace.version if workspace else 0,
        "can_write": state.can_write,
        "read_only_reason": state.reason or None,
        "current_keyword_set_version": (
            {
                "id": str(current_keyword_version.pk),
                "version_no": current_keyword_version.version_no,
                "item_count": current_keyword_version.item_count,
            }
            if current_keyword_version
            else None
        ),
        "draft_input_version": (
            {
                "id": str(workspace.draft_input_version_id),
                "version_no": workspace.draft_input_version.version_no,
                "item_count": workspace.draft_input_version.item_count,
            }
            if workspace
            else None
        ),
        "source_result_id": str(workspace.draft_source_result_id) if workspace else None,
        "current_distillation_version_no": (
            workspace.current_set.version_no if workspace and workspace.current_set else None
        ),
        "pending_item_count": len(pending_rows),
        "pending_items": [_keyword_payload(row) for row in pending_rows],
        "has_unconfirmed_result": has_unconfirmed_result,
        "items": [_item_payload(item) for item in draft_rows],
    }


def _version_payload(version):
    return {
        "id": str(version.pk),
        "version_no": version.version_no,
        "subject_version_id": str(version.subject_version_id),
        "keyword_set_version_id": str(version.input_keyword_set_version_id),
        "source_result_id": str(version.source_result_id),
        "item_count": version.item_count,
        "confirmed_at": version.confirmed_at,
        "items": [
            _item_payload(item)
            for item in version.items.select_related(
                "source_keyword", "canonical_keyword", "ai_canonical_keyword"
            ).order_by("sort_order", "id")
        ],
    }


class DistillationCreateView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, subject_id):
        serializer = DistillationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                job, created = create_distillation_job(
                    user_id=request.user.pk,
                    subject_id=subject_id,
                    idempotency_key=request.headers.get("Idempotency-Key", ""),
                    request_id=request.request_id,
                    **serializer.validated_data,
                )
                if created:
                    transaction.on_commit(lambda: _enqueue(job.pk, request.request_id))
        except DistillationError as exc:
            return _error(exc, request)
        except KeywordError as exc:
            return _error(exc, request)
        except QuotaError as exc:
            return _quota_error(exc, request)
        return _no_store(Response(_job_payload(job), status=HTTP_202_ACCEPTED))


class DistillationJobDetailView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, job_id):
        job = distillation_job_for_user_or_404(user=request.user, job_id=job_id)
        return _no_store(Response(_job_payload(job)))


class DistillationDraftView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        subject = subject_for_user_or_404(user=request.user, subject_id=subject_id)
        return _no_store(Response(_workspace_payload(user=request.user, subject=subject)))

    @method_decorator(csrf_protect)
    def patch(self, request, subject_id):
        serializer = DistillationDraftSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            workspace, _ = save_distillation_draft(
                user_id=request.user.pk,
                subject_id=subject_id,
                **serializer.validated_data,
            )
        except (DistillationError, KeywordError) as exc:
            return _error(exc, request)
        subject = subject_for_user_or_404(user=request.user, subject_id=subject_id)
        return _no_store(
            Response(_workspace_payload(user=request.user, subject=subject, workspace=workspace))
        )


class DistillationCurrentView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        version = current_distillation_for_user_or_404(
            user=request.user,
            subject_id=subject_id,
        )
        return _no_store(Response(_version_payload(version)))


class DistillationConfirmView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, subject_id):
        serializer = DistillationConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            _, version = confirm_distillation(
                user_id=request.user.pk,
                subject_id=subject_id,
                **serializer.validated_data,
            )
        except (DistillationError, KeywordError) as exc:
            return _error(exc, request)
        return _no_store(Response({"version": _version_payload(version)}, status=HTTP_201_CREATED))
