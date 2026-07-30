from django.core.cache import cache
from django.db import connection
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_503_SERVICE_UNAVAILABLE
from rest_framework.views import APIView


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
            pass

        healthy = all(checks.values())
        return Response(
            {
                "status": "ok" if healthy else "unavailable",
                "service": "xianwen-geo-api",
                "checks": checks,
            },
            status=HTTP_200_OK if healthy else HTTP_503_SERVICE_UNAVAILABLE,
        )
