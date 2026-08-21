import logging
from time import monotonic

from .context import reset_request_id, set_request_id
from .redaction import redact_request_path
from .request_ids import request_id_or_new

logger = logging.getLogger("xianwen.request")


class RequestIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request_id_or_new(request.META.get("HTTP_X_REQUEST_ID"))
        request.request_id = request_id
        token = set_request_id(request_id)
        started_at = monotonic()
        status_code = 500

        try:
            response = self.get_response(request)
            status_code = response.status_code
            response["X-Request-ID"] = request_id
            return response
        finally:
            logger.info(
                "请求完成",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": redact_request_path(request.path),
                    "status_code": status_code,
                    "duration_ms": round((monotonic() - started_at) * 1000, 2),
                },
            )
            reset_request_id(token)


class SecurityHeadersMiddleware:
    """Apply the frozen API security-header contract without exposing runtime config."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault(
            "Content-Security-Policy",
            "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        )
        response.setdefault("Referrer-Policy", "no-referrer")
        response.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        )
        response.setdefault("Cross-Origin-Resource-Policy", "same-site")
        response.setdefault("X-Permitted-Cross-Domain-Policies", "none")
        return response
