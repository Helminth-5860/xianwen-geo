from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.status import HTTP_409_CONFLICT, HTTP_422_UNPROCESSABLE_ENTITY
from rest_framework.views import APIView

from apps.admin_rbac.permissions import HasAdminPermission, HasSuperuserAdminSession
from apps.core.error_codes import ErrorCode
from apps.core.responses import error_response

from .credentials import (
    create_api_credential,
    list_active_credentials,
    rotate_api_credential,
    test_api_credential,
)
from .exceptions import AICredentialError, AIModelConfigError
from .models import AIModelRuntimeConfig, APICredential
from .serializers import (
    AIModelRuntimeConfigSerializer,
    AIModelRuntimeConfigUpdateSerializer,
    APICredentialCreateSerializer,
    APICredentialRotateSerializer,
    APICredentialSerializer,
    APICredentialTestSerializer,
    ExpectedAIModelConfigVersionSerializer,
    PauseAIModelSerializer,
)
from .services import set_model_enabled, set_model_paused, update_runtime_config

ERROR_STATUS = {
    "AI_MODEL_CONFIG_VERSION_CONFLICT": HTTP_409_CONFLICT,
    "AI_MODEL_CONFIG_STATE_CONFLICT": HTTP_409_CONFLICT,
    "AI_MODEL_CONFIG_INVALID": HTTP_422_UNPROCESSABLE_ENTITY,
    "AI_CREDENTIAL_ALREADY_EXISTS": HTTP_409_CONFLICT,
    "AI_CREDENTIAL_VERSION_CONFLICT": HTTP_409_CONFLICT,
    "AI_CREDENTIAL_STATE_CONFLICT": HTTP_409_CONFLICT,
    "AI_CREDENTIAL_INVALID": HTTP_422_UNPROCESSABLE_ENTITY,
    "AI_CREDENTIAL_CRYPTO_FAILURE": 503,
}


def _no_store(response):
    response["Cache-Control"] = "no-store"
    return response


def _error(exc: AIModelConfigError | AICredentialError, request):
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


class AdminAPICredentialListCreateView(APIView):
    permission_classes = [HasSuperuserAdminSession]

    def get(self, request):
        return _no_store(
            Response(APICredentialSerializer(list_active_credentials(), many=True).data)
        )

    @method_decorator(csrf_protect)
    def post(self, request):
        serializer = APICredentialCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            credential = create_api_credential(
                request=request,
                provider_key=serializer.validated_data["provider_key"],
                environment=serializer.validated_data["environment"],
                secret=serializer.validated_data["api_key"],
            )
        except AICredentialError as exc:
            return _error(exc, request)
        return _no_store(Response(APICredentialSerializer(credential).data, status=201))


class AdminAPICredentialRotateView(APIView):
    permission_classes = [HasSuperuserAdminSession]

    @method_decorator(csrf_protect)
    def post(self, request, credential_id):
        serializer = APICredentialRotateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            credential = rotate_api_credential(
                request=request,
                credential_id=credential_id,
                expected_version=serializer.validated_data["expected_version"],
                secret=serializer.validated_data["api_key"],
            )
        except AICredentialError as exc:
            if isinstance(exc.__cause__, APICredential.DoesNotExist):
                raise NotFound from exc
            return _error(exc, request)
        return _no_store(Response(APICredentialSerializer(credential).data))


class AdminAPICredentialTestView(APIView):
    permission_classes = [HasSuperuserAdminSession]

    @method_decorator(csrf_protect)
    def post(self, request, credential_id):
        serializer = APICredentialTestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = test_api_credential(
                request=request,
                credential_id=credential_id,
                expected_version=serializer.validated_data["expected_version"],
            )
        except AICredentialError as exc:
            if isinstance(exc.__cause__, APICredential.DoesNotExist):
                raise NotFound from exc
            return _error(exc, request)
        if not result.storage_valid:
            return _no_store(
                error_response(
                    ErrorCode.AI_CREDENTIAL_CRYPTO_FAILURE,
                    status_code=503,
                    request=request,
                )
            )
        payload = {
            "credential": APICredentialSerializer(result.credential).data,
            "storage_valid": True,
            "remote_validated": False,
        }
        return _no_store(Response(payload))
