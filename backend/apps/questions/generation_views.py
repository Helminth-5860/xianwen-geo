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
from apps.keywords.exceptions import KeywordError
from apps.keywords.services import keyword_write_state
from apps.quotas.exceptions import QuotaError
from apps.subjects.permissions import IsAvailableAuthenticatedUser
from apps.subjects.risk_services import SubjectRiskError
from apps.subjects.subject_services import subject_for_user_or_404

from .generation_exceptions import QuestionBankError
from .generation_serializers import (
    QuestionBankConfirmSerializer,
    QuestionDraftSaveSerializer,
    QuestionGenerationCreateSerializer,
)
from .generation_services import (
    _catalog_snapshots,
    confirm_question_bank,
    create_question_generation_job,
    current_question_bank_for_user_or_404,
    question_bank_version_for_user_or_404,
    question_bank_versions_for_user,
    question_bank_workspace_for_subject,
    question_generation_job_for_user_or_404,
    question_generation_quota_payload,
    save_question_bank_draft,
)
from .generation_tasks import execute_question_generation_task

logger = logging.getLogger(__name__)

ERROR_STATUS = {
    "QUESTION_BANK_VALUES_INVALID": HTTP_422_UNPROCESSABLE_ENTITY,
    "QUESTION_BANK_VERSION_CONFLICT": HTTP_409_CONFLICT,
    "QUESTION_BANK_INPUT_CONFLICT": HTTP_409_CONFLICT,
    "QUESTION_BANK_VERSION_NO_CHANGES": HTTP_409_CONFLICT,
    "QUESTION_GENERATION_IN_PROGRESS": HTTP_409_CONFLICT,
    "QUESTION_GENERATION_IDEMPOTENCY_CONFLICT": HTTP_409_CONFLICT,
    "QUESTION_GENERATION_REGENERATION_CONFIRMATION_REQUIRED": HTTP_409_CONFLICT,
    "QUESTION_GENERATION_INVALID_RESPONSE": HTTP_422_UNPROCESSABLE_ENTITY,
    "QUESTION_GENERATION_PROVIDER_UNAVAILABLE": HTTP_503_SERVICE_UNAVAILABLE,
    "PLAN_REQUIRED": HTTP_403_FORBIDDEN,
    "ACCOUNT_UNAVAILABLE": HTTP_403_FORBIDDEN,
    "SUBJECT_REVIEW_PENDING": HTTP_409_CONFLICT,
    "SUBJECT_REVIEW_REJECTED": HTTP_409_CONFLICT,
    "SUBJECT_RISK_CONFIG_INTEGRITY_ERROR": HTTP_503_SERVICE_UNAVAILABLE,
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
        execute_question_generation_task.apply_async(
            args=[str(job_id)],
            queue="ai_content",
            headers={"request_id": str(request_id), "correlation_id": str(request_id)},
        )
    except Exception:
        logger.exception(
            "question generation enqueue failed",
            extra={"context": {"job_id": str(job_id)}},
        )


def _job_payload(job):
    result = getattr(job, "result", None)
    return {
        "id": str(job.pk),
        "subject_id": str(job.subject_id),
        "subject_version_id": str(job.subject_version_id),
        "distillation_set_id": str(job.input_distillation_set_id),
        "status": job.status,
        "version": job.version,
        "stable_error_code": job.stable_error_code,
        "question_limit": job.question_limit,
        "billing": question_generation_quota_payload(job),
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


def _draft_item_payload(row):
    return {
        "id": str(row.pk),
        "text": row.text,
        "primary_category": {
            "id": str(row.primary_category_id),
            "key": row.primary_category.key,
            "name": row.primary_category.name,
        },
        "tag_ids": row.tag_ids,
        "keyword_ids": row.keyword_ids,
        "priority": row.priority,
        "question_type": row.question_type,
        "participates_in_scoring": row.participates_in_scoring,
        "ai_reason": row.ai_reason,
        "sort_order": row.sort_order,
    }


def _workspace_payload(*, user, subject, workspace=None):
    workspace = workspace or question_bank_workspace_for_subject(user=user, subject=subject)
    state = keyword_write_state(user=user, subject=subject)
    can_write = state.can_write and subject.status == subject.Status.ACTIVE
    read_only_reason = state.reason or ("subject_not_active" if not can_write else "")
    distillation_workspace = getattr(subject, "distillation_workspace", None)
    current_distillation = getattr(distillation_workspace, "current_set", None)
    limit = None
    if workspace and workspace.draft_source_result_id:
        limit = workspace.draft_source_result.job.question_limit
    categories, tags = _catalog_snapshots(subject)
    return {
        "version": workspace.version if workspace else 0,
        "catalog": {"categories": categories, "tags": tags},
        "can_write": can_write,
        "read_only_reason": read_only_reason or None,
        "question_limit": limit,
        "current_distillation_set": (
            {
                "id": str(current_distillation.pk),
                "version_no": current_distillation.version_no,
                "item_count": current_distillation.item_count,
            }
            if current_distillation
            else None
        ),
        "draft_input": (
            {
                "subject_version_id": str(workspace.draft_subject_version_id),
                "distillation_set_id": str(workspace.draft_distillation_set_id),
                "distillation_version_no": workspace.draft_distillation_set.version_no,
            }
            if workspace
            else None
        ),
        "source_result_id": str(workspace.draft_source_result_id)
        if workspace and workspace.draft_source_result_id
        else None,
        "current_question_bank_version_no": (
            workspace.current_version.version_no
            if workspace and workspace.current_version
            else None
        ),
        "items": (
            [
                _draft_item_payload(row)
                for row in workspace.draft_items.select_related("primary_category").order_by(
                    "sort_order", "id"
                )
            ]
            if workspace
            else []
        ),
    }


def _question_payload(row):
    return {
        "id": str(row.pk),
        "text": row.text,
        "primary_category": {
            "id": str(row.primary_category_id),
            "key": row.primary_category_key,
            "name": row.primary_category_name,
            "version": row.primary_category_version,
        },
        "tags": [
            {
                "id": str(link.tag_id),
                "key": link.tag_key,
                "name": link.tag_name,
                "version": link.tag_version,
            }
            for link in row.tag_links.all()
        ],
        "keywords": [
            {"id": str(link.keyword_id), "text": link.keyword_text}
            for link in row.keyword_links.all()
        ],
        "priority": row.priority,
        "question_type": row.question_type,
        "participates_in_scoring": row.participates_in_scoring,
        "ai_reason": row.ai_reason,
        "sort_order": row.sort_order,
    }


def _version_payload(version, *, include_items=True):
    payload = {
        "id": str(version.pk),
        "version_no": version.version_no,
        "subject_version_id": str(version.subject_version_id),
        "distillation_set_id": str(version.distillation_set_id),
        "source_result_id": str(version.source_result_id) if version.source_result_id else None,
        "item_count": version.item_count,
        "confirmed_at": version.confirmed_at,
    }
    if include_items:
        payload["items"] = [
            _question_payload(row)
            for row in version.questions.prefetch_related("tag_links", "keyword_links").order_by(
                "sort_order", "id"
            )
        ]
    return payload


class QuestionGenerationCreateView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, subject_id):
        serializer = QuestionGenerationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                job, created = create_question_generation_job(
                    user_id=request.user.pk,
                    subject_id=subject_id,
                    idempotency_key=request.headers.get("Idempotency-Key", ""),
                    request_id=request.request_id,
                    **serializer.validated_data,
                )
                if created:
                    transaction.on_commit(lambda: _enqueue(job.pk, request.request_id))
        except (QuestionBankError, KeywordError, SubjectRiskError) as exc:
            return _error(exc, request)
        except QuotaError as exc:
            return _quota_error(exc, request)
        return _no_store(Response(_job_payload(job), status=HTTP_202_ACCEPTED))


class QuestionGenerationJobDetailView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, job_id):
        return _no_store(
            Response(
                _job_payload(
                    question_generation_job_for_user_or_404(user=request.user, job_id=job_id)
                )
            )
        )


class QuestionBankDraftView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        subject = subject_for_user_or_404(user=request.user, subject_id=subject_id)
        return _no_store(Response(_workspace_payload(user=request.user, subject=subject)))

    @method_decorator(csrf_protect)
    def patch(self, request, subject_id):
        serializer = QuestionDraftSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            workspace, _ = save_question_bank_draft(
                user_id=request.user.pk, subject_id=subject_id, **serializer.validated_data
            )
        except (QuestionBankError, KeywordError) as exc:
            return _error(exc, request)
        subject = subject_for_user_or_404(user=request.user, subject_id=subject_id)
        return _no_store(
            Response(_workspace_payload(user=request.user, subject=subject, workspace=workspace))
        )


class QuestionBankConfirmView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, subject_id):
        serializer = QuestionBankConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            _, version = confirm_question_bank(
                user_id=request.user.pk, subject_id=subject_id, **serializer.validated_data
            )
        except (QuestionBankError, KeywordError) as exc:
            return _error(exc, request)
        return _no_store(Response({"version": _version_payload(version)}, status=HTTP_201_CREATED))


class QuestionBankCurrentView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        return _no_store(
            Response(
                _version_payload(
                    current_question_bank_for_user_or_404(user=request.user, subject_id=subject_id)
                )
            )
        )


class QuestionBankVersionListView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        rows = question_bank_versions_for_user(user=request.user, subject_id=subject_id)
        return _no_store(
            Response({"versions": [_version_payload(row, include_items=False) for row in rows]})
        )


class QuestionBankVersionDetailView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id, version_id):
        return _no_store(
            Response(
                _version_payload(
                    question_bank_version_for_user_or_404(
                        user=request.user,
                        subject_id=subject_id,
                        version_id=version_id,
                    )
                )
            )
        )
