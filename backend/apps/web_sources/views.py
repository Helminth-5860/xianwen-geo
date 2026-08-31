import logging

from django.conf import settings
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
from apps.subjects.permissions import IsAvailableAuthenticatedUser
from apps.subjects.subject_services import subject_for_user_or_404

from .exceptions import WebSourceError
from .models import WebSourceImport
from .serializers import (
    WebSourceConfirmSerializer,
    WebSourceImportRequestSerializer,
    WebSourceImportSerializer,
)
from .services import confirm_import, create_import, import_for_user_or_404
from .tasks import execute_import_task

logger = logging.getLogger(__name__)

ERROR_STATUS = {
    "WEB_SOURCE_URL_INVALID": HTTP_422_UNPROCESSABLE_ENTITY,
    "WEB_SOURCE_URL_NOT_ALLOWED": HTTP_422_UNPROCESSABLE_ENTITY,
    "WEB_SOURCE_CONTENT_UNSUPPORTED": HTTP_422_UNPROCESSABLE_ENTITY,
    "WEB_SOURCE_CONTENT_TOO_LARGE": HTTP_422_UNPROCESSABLE_ENTITY,
    "WEB_SOURCE_STATE_CONFLICT": HTTP_409_CONFLICT,
    "WEB_SOURCE_VERSION_CONFLICT": HTTP_409_CONFLICT,
    "WEB_SOURCE_IDEMPOTENCY_KEY_REQUIRED": HTTP_422_UNPROCESSABLE_ENTITY,
    "IDEMPOTENCY_CONFLICT": HTTP_409_CONFLICT,
    "RATE_LIMITED": HTTP_429_TOO_MANY_REQUESTS,
    "WEB_SOURCE_TEMPORARILY_UNAVAILABLE": HTTP_503_SERVICE_UNAVAILABLE,
    "WEB_SOURCE_FETCH_TEMPORARILY_UNAVAILABLE": HTTP_503_SERVICE_UNAVAILABLE,
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


def _enqueue_import(*, import_id, request_id):
    try:
        execute_import_task.apply_async(
            args=[str(import_id)],
            queue="web_fetch",
            headers={
                "request_id": str(request_id),
                "correlation_id": str(request_id),
            },
        )
    except Exception:
        # The durable queued row remains the source of truth. The periodic dispatcher
        # will retry delivery; no URL or response content is written to this log.
        logger.exception(
            "web source task enqueue failed",
            extra={"context": {"import_id": str(import_id)}},
        )


class WebSourceImportCreateView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request):
        if not settings.WEB_IMPORT_ENABLED:
            return error_response(
                ErrorCode.WEB_SOURCE_TEMPORARILY_UNAVAILABLE,
                status_code=HTTP_503_SERVICE_UNAVAILABLE,
                request=request,
            )
        serializer = WebSourceImportRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                row, created = create_import(
                    request=request,
                    user_id=request.user.pk,
                    subject_id=serializer.validated_data["subject_id"],
                    raw_url=serializer.validated_data["url"],
                    idempotency_key=request.headers.get("Idempotency-Key", ""),
                    request_id=request.request_id,
                )
                if created:
                    transaction.on_commit(
                        lambda: _enqueue_import(import_id=row.pk, request_id=request.request_id)
                    )
        except WebSourceError as exc:
            return _error(exc, request)
        return _no_store(Response(WebSourceImportSerializer(row).data, status=HTTP_202_ACCEPTED))


class WebSourceImportDetailView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, import_id):
        row = import_for_user_or_404(user=request.user, import_id=import_id)
        return _no_store(Response(WebSourceImportSerializer(row).data))


class SubjectWebSourceListView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        subject = subject_for_user_or_404(user=request.user, subject_id=subject_id)
        rows = WebSourceImport.objects.filter(
            subject=subject
        ).select_related("latest_parsed_version", "current_confirmed_version")
        return _no_store(Response({"results": WebSourceImportSerializer(rows, many=True).data}))


class WebSourceConfirmView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, import_id):
        serializer = WebSourceConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            row, parsed, created = confirm_import(
                user_id=request.user.pk,
                import_id=import_id,
                expected_version=serializer.validated_data["expected_version"],
                source_version_id=serializer.validated_data["source_parsed_version_id"],
                confirmed_text=serializer.validated_data["confirmed_text"],
                request_id=request.request_id,
            )
        except WebSourceError as exc:
            return _error(exc, request)
        return _no_store(
            Response(
                {
                    "version": row.version,
                    "confirmed_version": {"id": str(parsed.pk), "version_no": parsed.version_no},
                    "created": created,
                }
            )
        )
