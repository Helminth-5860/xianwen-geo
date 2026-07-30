import logging

from django.urls import include, path
from rest_framework import serializers
from rest_framework.exceptions import NotFound, PermissionDenied, Throttled
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.handlers import api_page_not_found, api_server_error

logger = logging.getLogger("tests.api")


class TestSerializer(serializers.Serializer):
    name = serializers.CharField()


class ValidationView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = TestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.validated_data)


class ProtectedView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"status": "authenticated"})


class ForbiddenView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        raise PermissionDenied()


class MissingView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        raise NotFound()


class ThrottledView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        raise Throttled(wait=3)


class GetOnlyView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"status": "ok"})


class ParseView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        return Response({"received": request.data})


class ExceptionView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        raise RuntimeError("sensitive SQL password and C:\\server\\secret.py")


class SensitiveLogView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        logger.info(
            "结构化上下文测试",
            extra={
                "context": {
                    "password": "test-password-value",
                    "access_token": "test-token-value",
                    "sms_code": "928314",
                    "error": {"code": "VALIDATION_ERROR"},
                }
            },
        )
        return Response({"status": "logged"})


urlpatterns = [
    path("api/v1/", include("apps.core.urls")),
    path("api/v1/test/validation/", ValidationView.as_view()),
    path("api/v1/test/protected/", ProtectedView.as_view()),
    path("api/v1/test/forbidden/", ForbiddenView.as_view()),
    path("api/v1/test/missing/", MissingView.as_view()),
    path("api/v1/test/throttled/", ThrottledView.as_view()),
    path("api/v1/test/get-only/", GetOnlyView.as_view()),
    path("api/v1/test/parse/", ParseView.as_view()),
    path("api/v1/test/exception/", ExceptionView.as_view()),
    path("api/v1/test/sensitive-log/", SensitiveLogView.as_view()),
]

handler404 = api_page_not_found
handler500 = api_server_error
