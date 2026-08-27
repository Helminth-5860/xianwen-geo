from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from django.http import Http404
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_201_CREATED,
    HTTP_202_ACCEPTED,
    HTTP_204_NO_CONTENT,
    HTTP_403_FORBIDDEN,
    HTTP_409_CONFLICT,
    HTTP_422_UNPROCESSABLE_ENTITY,
    HTTP_503_SERVICE_UNAVAILABLE,
)
from rest_framework.views import APIView

from apps.core.error_codes import ErrorCode
from apps.core.responses import error_response
from apps.documents.storage import storage_provider
from apps.quotas.exceptions import QuotaError
from apps.subjects.permissions import IsAvailableAuthenticatedUser
from apps.subjects.subject_services import subject_for_user_or_404

from .assistant import assistant_context_payload, respond_to_assistant
from .exceptions import AssistantError, GeoDetectionError, StrategyError
from .models import GeoDetectionQuestionSnapshot, GeoReport, ReportExport, ReportShare, StrategyNote
from .reports import (
    comparison,
    create_export,
    full_answer,
    prepare_report,
    question_group_page,
    report_for_user_or_404,
    report_history,
    report_payload,
    report_trends,
)
from .retests import QuickRetestBlocked, create_adjusted_retest, create_quick_retest
from .serializers import (
    AdjustedRetestSerializer,
    AssistantRespondSerializer,
    GeoDetectionSelectionSerializer,
    GeoRetestSerializer,
    ReportExportSerializer,
    ReportShareCreateSerializer,
    ReportShareUnlockSerializer,
    StrategyCreateSerializer,
    StrategyNoteDeleteSerializer,
    StrategyNoteSerializer,
    WhiteLabelSerializer,
)
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
from .sharing import (
    ShareError,
    close_report_share,
    create_report_share,
    public_share_payload,
    public_share_pdf,
    save_white_label,
    share_payload,
    unlock_report_share,
    white_label_payload,
)
from .strategy import (
    create_strategy_report,
    delete_strategy_note,
    fail_strategy_enqueue,
    put_strategy_note,
    strategy_for_user_or_404,
    strategy_list_payload,
    strategy_payload,
)
from .tasks import (
    dispatch_model_calls_task,
    execute_report_export_task,
    execute_strategy_report_task,
)

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
STRATEGY_ERROR_STATUS = {
    "STRATEGY_VALUES_INVALID": HTTP_422_UNPROCESSABLE_ENTITY,
    "STRATEGY_PROVIDER_UNAVAILABLE": HTTP_503_SERVICE_UNAVAILABLE,
}
ASSISTANT_ERROR_STATUS = {
    "ASSISTANT_VALUES_INVALID": HTTP_422_UNPROCESSABLE_ENTITY,
    "ASSISTANT_SCOPE_REFUSED": HTTP_403_FORBIDDEN,
    "ASSISTANT_SECURITY_REFUSED": HTTP_403_FORBIDDEN,
    "ASSISTANT_PROVIDER_UNAVAILABLE": HTTP_503_SERVICE_UNAVAILABLE,
    "ASSISTANT_INVALID_RESPONSE": HTTP_503_SERVICE_UNAVAILABLE,
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


def _strategy_error(exc: StrategyError, request):
    return error_response(
        ErrorCode(exc.code),
        status_code=STRATEGY_ERROR_STATUS.get(exc.code, HTTP_409_CONFLICT),
        request=request,
    )


def _assistant_error(exc: AssistantError, request):
    return error_response(
        ErrorCode(exc.code),
        status_code=ASSISTANT_ERROR_STATUS.get(exc.code, HTTP_409_CONFLICT),
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


class GeoDetectionReportView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, detection_id):
        job = detection_for_user_or_404(user=request.user, detection_id=detection_id)
        try:
            report = prepare_report(job=job)
            if report is None:
                raise ValueError
        except ValueError:
            return error_response(
                ErrorCode.GEO_DETECTION_STATE_CONFLICT,
                status_code=HTTP_409_CONFLICT,
                request=request,
            )
        return _no_store(Response(report_payload(report)))


class GeoReportDetailView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, report_id):
        return _no_store(
            Response(report_payload(report_for_user_or_404(user=request.user, report_id=report_id)))
        )


class GeoReportQuestionsView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, report_id):
        report = report_for_user_or_404(user=request.user, report_id=report_id)
        try:
            page = max(1, int(request.query_params.get("page", "1")))
        except ValueError:
            page = 1
        return _no_store(Response(question_group_page(report=report, page=page)))


class GeoReportQuestionView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, report_id, question_id):
        report = report_for_user_or_404(user=request.user, report_id=report_id)
        try:
            question = report.job.snapshot.questions.get(pk=question_id)
        except GeoDetectionQuestionSnapshot.DoesNotExist as exc:
            raise Http404 from exc
        page = question.sort_order // 10 + 1
        payload = question_group_page(report=report, page=page)
        try:
            result = next(
                row for row in payload["results"] if row["question_id"] == str(question_id)
            )
        except StopIteration as exc:
            raise Http404 from exc
        return _no_store(Response(result))


class GeoReportAnswerView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, report_id, call_id):
        report = report_for_user_or_404(user=request.user, report_id=report_id)
        return _no_store(Response(full_answer(report=report, call_id=call_id)))


class GeoModelCallResponseView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, call_id):
        try:
            report = GeoReport.objects.get(job__model_calls__pk=call_id, user=request.user)
        except GeoReport.DoesNotExist as exc:
            raise Http404 from exc
        return _no_store(Response(full_answer(report=report, call_id=call_id)))


class GeoReportHistoryView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        subject_for_user_or_404(user=request.user, subject_id=subject_id)
        return _no_store(
            Response({"items": report_history(user=request.user, subject_id=subject_id)})
        )


class GeoReportTrendsView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        subject_for_user_or_404(user=request.user, subject_id=subject_id)
        return _no_store(
            Response({"items": report_trends(user=request.user, subject_id=subject_id)})
        )


class GeoReportComparisonView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, report_id, other_id):
        current = report_for_user_or_404(user=request.user, report_id=report_id)
        baseline = report_for_user_or_404(user=request.user, report_id=other_id)
        if current.subject_id != baseline.subject_id:
            raise Http404
        return _no_store(
            Response(
                {
                    "current": report_payload(current),
                    "baseline": report_payload(baseline),
                    "comparison": comparison(current, baseline),
                }
            )
        )


class GeoReportExportView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, report_id):
        report = report_for_user_or_404(user=request.user, report_id=report_id)
        serializer = ReportExportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        export = create_export(report=report, user=request.user, **serializer.validated_data)
        transaction.on_commit(
            lambda: execute_report_export_task.apply_async(
                args=[str(export.pk)], queue="system_tasks"
            )
        )
        return Response({"id": str(export.pk), "status": export.status}, status=HTTP_202_ACCEPTED)


class GeoReportExportDetailView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, export_id):
        try:
            export = ReportExport.objects.select_related("report").get(
                pk=export_id, user=request.user
            )
        except ReportExport.DoesNotExist as exc:
            raise Http404 from exc
        data = {
            "id": str(export.pk),
            "report_id": str(export.report_id),
            "format": export.format,
            "status": export.status,
            "safe_error_code": export.safe_error_code,
            "download_url": None,
            "expires_at": export.expires_at,
            "expired": bool(export.expires_at and export.expires_at <= timezone.now()),
        }
        if export.status == ReportExport.Status.SUCCEEDED and not data["expired"]:
            content_types = {
                "pdf": "application/pdf",
                "word": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            }
            extensions = {"pdf": "pdf", "word": "docx", "excel": "xlsx"}
            data["download_url"] = storage_provider().create_download_url(
                key=export.object_key,
                filename=f"geo-report-{export.report_id}.{extensions[export.format]}",
                content_type=content_types[export.format],
            )
        return _no_store(Response(data))


def _retest_response(job, created):
    return _no_store(
        Response(
            {
                "detection_id": str(job.pk),
                "status": job.status,
                "replayed": not created,
            },
            status=HTTP_202_ACCEPTED,
        )
    )


def _quick_retest_error(exc, request):
    return error_response(
        ErrorCode.GEO_DETECTION_PROVIDER_UNAVAILABLE,
        status_code=HTTP_409_CONFLICT,
        request=request,
        details={
            "model_key": exc.model_key,
            "reason": exc.reason,
            "suggested_actions": ["retry_later", "restore_access", "use_adjusted_retest"],
        },
    )


class GeoReportQuickRetestView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, report_id):
        try:
            job, created = create_quick_retest(
                user_id=request.user.pk,
                baseline_report_id=report_id,
                idempotency_key=request.headers.get("Idempotency-Key", ""),
                request_id=request.request_id,
            )
        except QuickRetestBlocked as exc:
            return _quick_retest_error(exc, request)
        except GeoDetectionError as exc:
            return _error(exc, request)
        except QuotaError as exc:
            return _quota_error(exc, request)
        if created:
            transaction.on_commit(_dispatch_after_commit)
        return _retest_response(job, created)


class GeoReportAdjustedRetestView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, report_id):
        serializer = AdjustedRetestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            job, created = create_adjusted_retest(
                user_id=request.user.pk,
                baseline_report_id=report_id,
                idempotency_key=request.headers.get("Idempotency-Key", ""),
                request_id=request.request_id,
                question_ids=serializer.validated_data["question_ids"],
                model_ids=serializer.validated_data["model_ids"],
            )
        except GeoDetectionError as exc:
            return _error(exc, request)
        except QuotaError as exc:
            return _quota_error(exc, request)
        if created:
            transaction.on_commit(_dispatch_after_commit)
        return _retest_response(job, created)


class GeoReportRetestView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, report_id):
        serializer = GeoRetestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        mode = serializer.validated_data["mode"]
        try:
            if mode == "quick":
                job, created = create_quick_retest(
                    user_id=request.user.pk,
                    baseline_report_id=report_id,
                    idempotency_key=request.headers.get("Idempotency-Key", ""),
                    request_id=request.request_id,
                )
            else:
                job, created = create_adjusted_retest(
                    user_id=request.user.pk,
                    baseline_report_id=report_id,
                    idempotency_key=request.headers.get("Idempotency-Key", ""),
                    request_id=request.request_id,
                    question_ids=serializer.validated_data["question_ids"],
                    model_ids=serializer.validated_data["model_ids"],
                )
        except QuickRetestBlocked as exc:
            return _quick_retest_error(exc, request)
        except GeoDetectionError as exc:
            return _error(exc, request)
        except QuotaError as exc:
            return _quota_error(exc, request)
        if created:
            transaction.on_commit(_dispatch_after_commit)
        return _retest_response(job, created)


def _enqueue_strategy(strategy_id, request_id):
    try:
        execute_strategy_report_task.apply_async(
            args=[str(strategy_id)],
            queue="ai_content",
            headers={"request_id": str(request_id), "correlation_id": str(request_id)},
        )
    except Exception:
        logger.exception(
            "strategy generation enqueue failed",
            extra={"context": {"strategy_id": str(strategy_id)}},
        )
        fail_strategy_enqueue(strategy_id=strategy_id)


class GeoReportStrategiesView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, report_id):
        report = report_for_user_or_404(user=request.user, report_id=report_id)
        return _no_store(Response(strategy_list_payload(user=request.user, report=report)))

    @method_decorator(csrf_protect)
    def post(self, request, report_id):
        serializer = StrategyCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                strategy, created = create_strategy_report(
                    user_id=request.user.pk,
                    report_id=report_id,
                    period=serializer.validated_data["period"],
                    custom_days=serializer.validated_data.get("custom_days"),
                    regenerate=serializer.validated_data["regenerate"],
                    idempotency_key=request.headers.get("Idempotency-Key", ""),
                    request_id=request.request_id,
                )
                if created:
                    transaction.on_commit(
                        lambda: _enqueue_strategy(strategy.pk, request.request_id)
                    )
        except StrategyError as exc:
            return _strategy_error(exc, request)
        except QuotaError as exc:
            return _quota_error(exc, request)
        return _no_store(Response(strategy_payload(strategy), status=HTTP_202_ACCEPTED))


class StrategyDetailView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, strategy_id):
        strategy = strategy_for_user_or_404(user=request.user, strategy_id=strategy_id)
        return _no_store(Response(strategy_payload(strategy)))


class StrategyNoteView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, strategy_id):
        strategy = strategy_for_user_or_404(user=request.user, strategy_id=strategy_id)
        try:
            note = strategy.note
        except StrategyNote.DoesNotExist:
            raise Http404 from None
        return _no_store(
            Response({"text": note.text, "version": note.version, "updated_at": note.updated_at})
        )

    @method_decorator(csrf_protect)
    def put(self, request, strategy_id):
        return self._write(request, strategy_id)

    @method_decorator(csrf_protect)
    def patch(self, request, strategy_id):
        return self._write(request, strategy_id)

    def _write(self, request, strategy_id):
        serializer = StrategyNoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            note = put_strategy_note(
                user=request.user,
                strategy_id=strategy_id,
                **serializer.validated_data,
            )
        except StrategyError as exc:
            return _strategy_error(exc, request)
        return _no_store(
            Response({"text": note.text, "version": note.version, "updated_at": note.updated_at})
        )

    @method_decorator(csrf_protect)
    def delete(self, request, strategy_id):
        serializer = StrategyNoteDeleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            delete_strategy_note(
                user=request.user,
                strategy_id=strategy_id,
                **serializer.validated_data,
            )
        except StrategyError as exc:
            return _strategy_error(exc, request)
        return _no_store(Response(status=HTTP_204_NO_CONTENT))


class AssistantContextView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request):
        try:
            payload = assistant_context_payload(user=request.user)
        except GeoDetectionError as exc:
            return _error(exc, request)
        return _no_store(Response(payload))


class AssistantRespondView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request):
        serializer = AssistantRespondSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            reply = respond_to_assistant(
                user_id=request.user.pk,
                idempotency_key=request.headers.get("Idempotency-Key", ""),
                request_id=request.request_id,
                **serializer.validated_data,
            )
        except AssistantError as exc:
            return _assistant_error(exc, request)
        except QuotaError as exc:
            return _quota_error(exc, request)
        return _no_store(
            Response(
                {
                    "answer": reply.answer,
                    "suggested_actions": reply.suggested_actions,
                    "remaining_messages": reply.remaining_messages,
                    "usage_event_id": reply.usage_event_id,
                    "history_persisted": False,
                }
            )
        )


def _share_error(exc: ShareError, request):
    code = (
        ErrorCode.PERMISSION_DENIED
        if exc.status in {403, 410}
        else ErrorCode.RATE_LIMITED
        if exc.status == 429
        else ErrorCode.VALIDATION_ERROR
        if exc.status == 422
        else ErrorCode.SERVICE_TEMPORARILY_UNAVAILABLE
    )
    return error_response(
        code,
        status_code=exc.status,
        request=request,
        message=exc.code,
        details={"share_code": exc.code},
    )


class SubjectWhiteLabelView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        subject = subject_for_user_or_404(user=request.user, subject_id=subject_id)
        return _no_store(Response(white_label_payload(user=request.user, subject=subject)))

    @method_decorator(csrf_protect)
    def put(self, request, subject_id):
        serializer = WhiteLabelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            save_white_label(user=request.user, subject_id=subject_id, **serializer.validated_data)
        except ShareError as exc:
            return _share_error(exc, request)
        subject = subject_for_user_or_404(user=request.user, subject_id=subject_id)
        return _no_store(Response(white_label_payload(user=request.user, subject=subject)))


class GeoReportSharesView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, report_id):
        report = report_for_user_or_404(user=request.user, report_id=report_id)
        page = max(1, int(request.query_params.get("page", "1")))
        page_size = min(100, max(1, int(request.query_params.get("page_size", "20"))))
        query = ReportShare.objects.filter(user=request.user, report=report)
        count = query.count()
        rows = query[(page - 1) * page_size : page * page_size]
        return _no_store(
            Response(
                {
                    "items": [share_payload(row) for row in rows],
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
    def post(self, request, report_id):
        serializer = ReportShareCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            share, token = create_report_share(
                user=request.user, report_id=report_id, **serializer.validated_data
            )
        except ShareError as exc:
            return _share_error(exc, request)
        payload = share_payload(share)
        payload["url"] = f"/public/report-shares/{token}"
        payload["token_returned_once"] = True
        return _no_store(Response(payload, status=HTTP_201_CREATED))


class ReportShareCloseView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def delete(self, request, share_id):
        share = close_report_share(user=request.user, share_id=share_id)
        return _no_store(Response(share_payload(share)))


class PublicReportShareView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, token):
        try:
            _, payload = public_share_payload(token=token, request=request)
        except ShareError as exc:
            return _share_error(exc, request)
        return _no_store(Response(payload))


class PublicReportShareUnlockView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, token):
        serializer = ReportShareUnlockSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            share, signed = unlock_report_share(
                token=token, request=request, **serializer.validated_data
            )
        except ShareError as exc:
            return _share_error(exc, request)
        response = _no_store(
            Response({"unlocked": True, "expires_in": settings.REPORT_SHARE_SESSION_TTL_SECONDS})
        )
        response.set_cookie(
            f"xw_report_share_{share.pk.hex}",
            signed,
            max_age=settings.REPORT_SHARE_SESSION_TTL_SECONDS,
            httponly=True,
            secure=settings.SESSION_COOKIE_SECURE,
            samesite="Lax",
            path=f"/api/v1/public/report-shares/{token}",
        )
        return response


class PublicReportSharePdfView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, token):
        try:
            url = public_share_pdf(token=token, request=request)
        except ShareError as exc:
            return _share_error(exc, request)
        return _no_store(Response({"download_url": url}))
