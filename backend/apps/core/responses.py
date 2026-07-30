from collections.abc import Mapping
from typing import Any

from rest_framework.response import Response

from .context import get_request_id
from .error_codes import ERROR_MESSAGES, ErrorCode
from .request_ids import new_request_id


def current_request_id(request=None) -> str:
    return getattr(request, "request_id", None) or get_request_id() or new_request_id()


def error_envelope(
    code: ErrorCode,
    *,
    request=None,
    message: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "success": False,
        "error": {
            "code": code.value,
            "message": message or ERROR_MESSAGES[code],
            "details": dict(details or {}),
        },
        "request_id": current_request_id(request),
    }


def error_response(
    code: ErrorCode,
    *,
    status_code: int,
    request=None,
    message: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> Response:
    return Response(
        error_envelope(
            code,
            request=request,
            message=message,
            details=details,
        ),
        status=status_code,
    )
