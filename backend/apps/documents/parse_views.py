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
from apps.subjects.permissions import IsAvailableAuthenticatedUser

from .parse_exceptions import DocumentParseError
from .parse_serializers import (
    ConfirmParseSerializer,
    ParseJobSerializer,
    ParseRequestSerializer,
    serialize_parse_result,
)
from .parse_services import (
    confirm_parsed_text,
    create_parse_job,
    parse_result_for_user,
)
from .tasks import execute_parse_job

ERROR_STATUS = {
    "DOCUMENT_PARSE_IDEMPOTENCY_KEY_REQUIRED": HTTP_422_UNPROCESSABLE_ENTITY,
    "IDEMPOTENCY_CONFLICT": HTTP_409_CONFLICT,
    "DOCUMENT_PARSE_STATE_CONFLICT": HTTP_409_CONFLICT,
    "DOCUMENT_PARSE_VERSION_CONFLICT": HTTP_409_CONFLICT,
    "DOCUMENT_PARSE_CONTENT_INVALID": HTTP_422_UNPROCESSABLE_ENTITY,
    "DOCUMENT_PARSE_SECURITY_REJECTED": HTTP_422_UNPROCESSABLE_ENTITY,
    "DOCUMENT_OCR_UNAVAILABLE": HTTP_503_SERVICE_UNAVAILABLE,
    "DOCUMENT_PARSE_TEMPORARILY_UNAVAILABLE": HTTP_503_SERVICE_UNAVAILABLE,
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


class DocumentParseView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, document_id):
        serializer = ParseRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            job, created = create_parse_job(
                user_id=request.user.pk,
                document_id=document_id,
                document_version_id=serializer.validated_data["document_version_id"],
                idempotency_key=request.headers.get("Idempotency-Key", ""),
                request_id=request.request_id,
            )
        except DocumentParseError as exc:
            return _error(exc, request)
        if created:
            transaction.on_commit(
                lambda: execute_parse_job.apply_async(
                    args=[str(job.pk)],
                    queue="file_processing",
                    headers={
                        "request_id": str(request.request_id),
                        "correlation_id": str(request.request_id),
                    },
                )
            )
        return _no_store(Response(ParseJobSerializer(job).data, status=HTTP_202_ACCEPTED))


class DocumentParseResultView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, document_id):
        _, job, state = parse_result_for_user(user=request.user, document_id=document_id)
        return _no_store(Response(serialize_parse_result(job=job, state=state)))


class DocumentConfirmParseView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, document_id):
        serializer = ConfirmParseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            state, parsed, created = confirm_parsed_text(
                user_id=request.user.pk,
                document_id=document_id,
                expected_parse_state_version=serializer.validated_data[
                    "expected_parse_state_version"
                ],
                source_parsed_version_id=serializer.validated_data["source_parsed_version_id"],
                confirmed_text=serializer.validated_data["confirmed_text"],
                request_id=request.request_id,
            )
        except DocumentParseError as exc:
            return _error(exc, request)
        return _no_store(
            Response(
                {
                    "parse_state_version": state.version,
                    "confirmed_version": {
                        "id": str(parsed.pk),
                        "version_no": parsed.version_no,
                    },
                    "created": created,
                }
            )
        )
