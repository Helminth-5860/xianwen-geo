from django.http import FileResponse, HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import HTTP_503_SERVICE_UNAVAILABLE
from rest_framework.views import APIView

from apps.core.error_codes import ErrorCode
from apps.core.responses import error_response
from apps.documents.exceptions import FileStorageUnavailable
from apps.documents.storage import storage_provider

from .permissions import HasAdminSession
from .sales_contact_serializers import (
    SalesContactEnabledSerializer,
    SalesContactUploadSerializer,
)
from .sales_contacts import (
    UNCONFIGURED_MESSAGE,
    configuration_from_media_token,
    get_admin_configuration,
    media_url,
    resolve_customer_configuration,
    save_qr_code,
    set_configuration_enabled,
    validate_qr_code,
)


def _admin_payload(request, config):
    return {
        "scope": "global" if request.user.is_superuser else "agent",
        "configured": bool(config and config.object_key),
        "enabled": bool(config and config.enabled),
        "qr_code_url": (
            media_url(request, config, allow_disabled=True)
            if config is not None and config.object_key
            else None
        ),
        "updated_at": config.updated_at.isoformat() if config is not None else None,
    }


@method_decorator(csrf_protect, name="dispatch")
class AdminSalesContactView(APIView):
    permission_classes = [HasAdminSession]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        return Response(_admin_payload(request, get_admin_configuration(request.admin_context)))

    def put(self, request):
        serializer = SalesContactUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        qr_code = validate_qr_code(serializer.validated_data["qr_code"])
        try:
            config = save_qr_code(
                context=request.admin_context,
                request=request,
                qr_code=qr_code,
                enabled=serializer.validated_data["enabled"],
            )
        except FileStorageUnavailable:
            return error_response(
                ErrorCode.FILE_STORAGE_UNAVAILABLE,
                status_code=HTTP_503_SERVICE_UNAVAILABLE,
                request=request,
            )
        return Response(_admin_payload(request, config))

    def patch(self, request):
        serializer = SalesContactEnabledSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        config = set_configuration_enabled(
            context=request.admin_context,
            request=request,
            enabled=serializer.validated_data["enabled"],
        )
        return Response(_admin_payload(request, config))


class CustomerSalesContactView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        config = resolve_customer_configuration(request.user)
        if config is None:
            return Response({"configured": False, "message": UNCONFIGURED_MESSAGE})
        return Response(
            {
                "configured": True,
                "qr_code_url": media_url(request, config),
            }
        )


class SalesContactMediaView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        config = configuration_from_media_token(request.query_params.get("token", ""))
        if config is None:
            return HttpResponse(status=404)
        try:
            source = storage_provider().open_object(config.object_key)
        except FileStorageUnavailable:
            return HttpResponse(status=503)
        response = FileResponse(
            source,
            as_attachment=False,
            filename="sales-wechat-qr",
            content_type=config.mime_type,
        )
        response["Content-Length"] = str(config.size_bytes)
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "default-src 'none'; img-src 'self'"
        return response
