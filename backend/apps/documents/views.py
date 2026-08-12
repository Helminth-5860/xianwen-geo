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

from .exceptions import FileBusinessError
from .serializers import (
    UploadIntentCompleteSerializer,
    UploadIntentCreateSerializer,
    UploadIntentSerializer,
    UserDocumentSerializer,
)
from .services import (
    complete_upload_intent,
    create_download_intent,
    create_upload_intent,
    document_for_user_or_404,
    documents_for_subject,
    intent_for_user_or_404,
)

ERROR_STATUS = {
    "FILE_IDEMPOTENCY_KEY_REQUIRED": HTTP_422_UNPROCESSABLE_ENTITY,
    "FILE_STATE_CONFLICT": HTTP_409_CONFLICT,
    "FILE_VERSION_CONFLICT": HTTP_409_CONFLICT,
    "FILE_TYPE_NOT_ALLOWED": HTTP_422_UNPROCESSABLE_ENTITY,
    "FILE_SIZE_INVALID": HTTP_422_UNPROCESSABLE_ENTITY,
    "FILE_CONTENT_INVALID": HTTP_422_UNPROCESSABLE_ENTITY,
    "FILE_SECURITY_REJECTED": HTTP_422_UNPROCESSABLE_ENTITY,
    "FILE_STORAGE_UNAVAILABLE": HTTP_503_SERVICE_UNAVAILABLE,
    "IDEMPOTENCY_CONFLICT": HTTP_409_CONFLICT,
    "QUOTA_INSUFFICIENT": HTTP_409_CONFLICT,
    "SUBSCRIPTION_UNAVAILABLE": HTTP_403_FORBIDDEN,
    "QUOTA_STATE_CONFLICT": HTTP_409_CONFLICT,
    "QUOTA_HOLD_STATE_CONFLICT": HTTP_409_CONFLICT,
    "QUOTA_BUSINESS_ALREADY_HELD": HTTP_409_CONFLICT,
}


def _error(exc, request):
    code = exc.code if exc.code in ErrorCode._value2member_map_ else "FILE_STATE_CONFLICT"
    return error_response(
        ErrorCode(code), status_code=ERROR_STATUS.get(exc.code, HTTP_409_CONFLICT), request=request
    )


def _no_store(response):
    response["Cache-Control"] = "no-store"
    return response


class UploadIntentListView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request):
        serializer = UploadIntentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data["purpose"] != "subject_library":
            return _error(type("E", (), {"code": "FILE_STATE_CONFLICT"})(), request)
        try:
            result = create_upload_intent(
                user_id=request.user.pk,
                subject_id=serializer.validated_data["subject_id"],
                filename=serializer.validated_data["filename"],
                content_type=serializer.validated_data["content_type"],
                declared_size=serializer.validated_data["size_bytes"],
                idempotency_key=request.headers.get("Idempotency-Key", ""),
                request_id=request.request_id,
            )
        except (FileBusinessError, QuotaError) as exc:
            return _error(exc, request)
        data: dict[str, object] = {
            "intent": UploadIntentSerializer(result.intent).data,
            "upload": None,
        }
        if result.upload is not None:
            data["upload"] = {
                "method": "POST",
                "url": result.upload.url,
                "fields": result.upload.fields,
                "expires_in": result.upload.expires_in,
            }
        return _no_store(Response(data, status=HTTP_201_CREATED))


class UploadIntentDetailView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, intent_id):
        intent = intent_for_user_or_404(user=request.user, intent_id=intent_id)
        return _no_store(Response(UploadIntentSerializer(intent).data))


class UploadIntentCompleteView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, intent_id):
        serializer = UploadIntentCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            intent = complete_upload_intent(
                user=request.user,
                intent_id=intent_id,
                expected_version=serializer.validated_data["expected_version"],
                request_id=request.request_id,
            )
        except FileBusinessError as exc:
            return _error(exc, request)
        return _no_store(Response(UploadIntentSerializer(intent).data, status=HTTP_202_ACCEPTED))


class SubjectDocumentListView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        documents = documents_for_subject(user=request.user, subject_id=subject_id)
        return Response({"documents": UserDocumentSerializer(documents, many=True).data})


class DocumentDownloadIntentView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, document_id):
        document_for_user_or_404(user=request.user, document_id=document_id)
        try:
            url, expires_in = create_download_intent(user=request.user, document_id=document_id)
        except FileBusinessError as exc:
            return _error(exc, request)
        return _no_store(Response({"url": url, "expires_in": expires_in}))
