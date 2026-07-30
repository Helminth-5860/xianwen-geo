from django.core.cache import cache
from django.db import connection
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.status import HTTP_503_SERVICE_UNAVAILABLE
from rest_framework.views import APIView

from .error_codes import ErrorCode
from .responses import error_response


class HealthCheckView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        checks = {"database": False, "redis": False}

        try:
            connection.ensure_connection()
            checks["database"] = True
            cache.set("health-check", "ok", timeout=5)
            checks["redis"] = cache.get("health-check") == "ok"
        except Exception:
            return error_response(
                ErrorCode.SERVICE_TEMPORARILY_UNAVAILABLE,
                status_code=HTTP_503_SERVICE_UNAVAILABLE,
                request=request,
                details={"checks": checks},
            )

        return Response({"status": "ok"})
