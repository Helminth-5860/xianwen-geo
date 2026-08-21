import logging

from django.http import JsonResponse
from django.views.defaults import page_not_found, server_error
from rest_framework import status

from .error_codes import ErrorCode
from .redaction import redact_request_path
from .responses import error_envelope

logger = logging.getLogger("xianwen.api")


def api_page_not_found(request, exception):
    if not request.path.startswith("/api/v1/"):
        return page_not_found(request, exception)
    return JsonResponse(
        error_envelope(ErrorCode.RESOURCE_NOT_FOUND, request=request),
        status=status.HTTP_404_NOT_FOUND,
    )


def api_server_error(request):
    if not request.path.startswith("/api/v1/"):
        return server_error(request)
    logger.error(
        "未处理的 Django 异常",
        exc_info=True,
        extra={
            "exception_type": "UnhandledDjangoException",
            "path": redact_request_path(request.path),
        },
    )
    return JsonResponse(
        error_envelope(ErrorCode.INTERNAL_ERROR, request=request),
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
