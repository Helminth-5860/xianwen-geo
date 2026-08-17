from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.status import HTTP_409_CONFLICT, HTTP_422_UNPROCESSABLE_ENTITY
from rest_framework.views import APIView

from apps.admin_rbac.permissions import HasAdminPermission
from apps.core.error_codes import ErrorCode
from apps.core.responses import error_response

from .exceptions import AIModelConfigError
from .models import AIModelRuntimeConfig
from .serializers import (
    AIModelRuntimeConfigSerializer,
    AIModelRuntimeConfigUpdateSerializer,
    ExpectedAIModelConfigVersionSerializer,
    PauseAIModelSerializer,
)
from .services import set_model_enabled, set_model_paused, update_runtime_config

ERROR_STATUS = {
    "AI_MODEL_CONFIG_VERSION_CONFLICT": HTTP_409_CONFLICT,
    "AI_MODEL_CONFIG_STATE_CONFLICT": HTTP_409_CONFLICT,
    "AI_MODEL_CONFIG_INVALID": HTTP_422_UNPROCESSABLE_ENTITY,
}


def _no_store(response):
    response["Cache-Control"] = "no-store"
    return response


def _error(exc: AIModelConfigError, request):
    return error_response(
        ErrorCode(exc.code),
        status_code=ERROR_STATUS.get(exc.code, HTTP_409_CONFLICT),
        request=request,
    )


def _rows():
    return AIModelRuntimeConfig.objects.select_related("model__provider").order_by(
        "sort_order", "model__model_key"
    )


def _config_or_404(model_id):
    try:
        return _rows().get(model_id=model_id)
    except AIModelRuntimeConfig.DoesNotExist as exc:
        raise NotFound from exc


class AdminAIModelListView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "models.list"

    def get(self, request):
        return _no_store(Response(AIModelRuntimeConfigSerializer(_rows(), many=True).data))


class AdminAIModelDetailView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "models.list"

    def get(self, request, model_id):
        return _no_store(Response(AIModelRuntimeConfigSerializer(_config_or_404(model_id)).data))


class AdminAIModelRuntimeConfigListView(AdminAIModelListView):
    pass


class AdminAIModelRuntimeConfigDetailView(APIView):
    permission_classes = [HasAdminPermission]
    required_permissions_by_method = {"GET": "models.list", "PATCH": "models.manage"}

    def get(self, request, model_id):
        return _no_store(Response(AIModelRuntimeConfigSerializer(_config_or_404(model_id)).data))

    @method_decorator(csrf_protect)
    def patch(self, request, model_id):
        serializer = AIModelRuntimeConfigUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            config = update_runtime_config(
                request=request, model_id=model_id, data=dict(serializer.validated_data)
            )
        except AIModelRuntimeConfig.DoesNotExist as exc:
            raise NotFound from exc
        except AIModelConfigError as exc:
            return _error(exc, request)
        return _no_store(Response(AIModelRuntimeConfigSerializer(config).data))


class AdminAIModelEnabledView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "models.manage"
    enabled = False

    @method_decorator(csrf_protect)
    def post(self, request, model_id):
        serializer = ExpectedAIModelConfigVersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            config = set_model_enabled(
                request=request,
                model_id=model_id,
                enabled=self.enabled,
                expected_version=serializer.validated_data["expected_version"],
            )
        except AIModelRuntimeConfig.DoesNotExist as exc:
            raise NotFound from exc
        except AIModelConfigError as exc:
            return _error(exc, request)
        return _no_store(Response(AIModelRuntimeConfigSerializer(config).data))


class AdminAIModelEnableView(AdminAIModelEnabledView):
    enabled = True


class AdminAIModelDisableView(AdminAIModelEnabledView):
    enabled = False


class AdminAIModelPausedView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "models.manage"
    paused = False

    @method_decorator(csrf_protect)
    def post(self, request, model_id):
        serializer_class = (
            PauseAIModelSerializer if self.paused else ExpectedAIModelConfigVersionSerializer
        )
        serializer = serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            config = set_model_paused(
                request=request,
                model_id=model_id,
                paused=self.paused,
                expected_version=serializer.validated_data["expected_version"],
                reason=serializer.validated_data.get("reason", ""),
            )
        except AIModelRuntimeConfig.DoesNotExist as exc:
            raise NotFound from exc
        except AIModelConfigError as exc:
            return _error(exc, request)
        return _no_store(Response(AIModelRuntimeConfigSerializer(config).data))


class AdminAIModelPauseView(AdminAIModelPausedView):
    paused = True


class AdminAIModelUnpauseView(AdminAIModelPausedView):
    paused = False
