import logging
from collections.abc import Mapping
from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404, JsonResponse
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import set_rollback

from .error_codes import ErrorCode
from .responses import error_envelope

logger = logging.getLogger("xianwen.api")


def normalize_validation_errors(detail: Any) -> dict[str, Any]:
    def normalize(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {str(key): normalize(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [normalize(item) for item in value]
        return {
            "message": str(value),
            "code": getattr(value, "code", "invalid"),
        }

    return {"fields": normalize(detail)}


def api_exception_handler(exc: Exception, context: dict) -> Response:
    request = context.get("request")

    if isinstance(exc, (exceptions.NotAuthenticated, exceptions.AuthenticationFailed)):
        code = ErrorCode.AUTH_REQUIRED
        status_code = status.HTTP_401_UNAUTHORIZED
        details = {}
    elif isinstance(exc, (exceptions.PermissionDenied, DjangoPermissionDenied)):
        code = ErrorCode.PERMISSION_DENIED
        status_code = status.HTTP_403_FORBIDDEN
        details = {}
    elif isinstance(exc, (exceptions.NotFound, Http404)):
        code = ErrorCode.RESOURCE_NOT_FOUND
        status_code = status.HTTP_404_NOT_FOUND
        details = {}
    elif isinstance(exc, exceptions.MethodNotAllowed):
        code = ErrorCode.METHOD_NOT_ALLOWED
        status_code = status.HTTP_405_METHOD_NOT_ALLOWED
        details = {}
    elif isinstance(exc, exceptions.ParseError):
        code = ErrorCode.INVALID_JSON
        status_code = status.HTTP_400_BAD_REQUEST
        details = {}
    elif isinstance(exc, exceptions.ValidationError):
        code = ErrorCode.VALIDATION_ERROR
        status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        details = normalize_validation_errors(exc.detail)
    elif isinstance(exc, exceptions.Throttled):
        code = ErrorCode.RATE_LIMITED
        status_code = status.HTTP_429_TOO_MANY_REQUESTS
        details = {"retry_after": exc.wait} if exc.wait is not None else {}
    else:
        code = ErrorCode.INTERNAL_ERROR
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        details = {}
        logger.error(
            "未处理的 API 异常",
            exc_info=(type(exc), exc, exc.__traceback__),
            extra={
                "exception_type": type(exc).__name__,
                "path": getattr(request, "path", ""),
            },
        )

    set_rollback()
    return Response(
        error_envelope(code, request=request, details=details),
        status=status_code,
    )


def csrf_failure(request, reason=""):
    logger.warning(
        "CSRF 验证失败",
        extra={"path": request.path, "exception_type": "CsrfFailure"},
    )
    return JsonResponse(
        error_envelope(ErrorCode.CSRF_FAILED, request=request),
        status=status.HTTP_403_FORBIDDEN,
    )
