from django.db.models import Q
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.status import HTTP_409_CONFLICT, HTTP_422_UNPROCESSABLE_ENTITY
from rest_framework.views import APIView

from apps.admin_rbac.permissions import HasAdminPermission
from apps.core.error_codes import ErrorCode
from apps.core.responses import error_response

from .models import SubjectType
from .permissions import IsAvailableAuthenticatedUser
from .serializers import (
    CustomFieldCreateSerializer,
    ExpectedSubjectTypeVersionsSerializer,
    FieldConfigUpdateSerializer,
    FieldOptionCreateSerializer,
    FieldOptionUpdateSerializer,
    FieldOrderSerializer,
    PublicFormSchemaSerializer,
    PublicSubjectTypeSerializer,
    SubjectFieldOptionSerializer,
    SubjectTypeCreateSerializer,
    SubjectTypeDetailSerializer,
    SubjectTypeFieldConfigSerializer,
    SubjectTypeSummarySerializer,
    SubjectTypeUpdateSerializer,
)
from .services import (
    SubjectDomainError,
    create_custom_field,
    create_field_option,
    create_subject_type,
    reorder_fields,
    set_subject_type_status,
    update_field_config,
    update_field_option,
    update_subject_type,
)

ERROR_STATUS = {
    "SUBJECT_TYPE_VERSION_CONFLICT": HTTP_409_CONFLICT,
    "SUBJECT_SCHEMA_VERSION_CONFLICT": HTTP_409_CONFLICT,
    "SUBJECT_TYPE_KEY_CONFLICT": HTTP_409_CONFLICT,
    "SUBJECT_FIELD_KEY_CONFLICT": HTTP_409_CONFLICT,
    "SUBJECT_FIELD_CONFIG_INVALID": HTTP_422_UNPROCESSABLE_ENTITY,
    "SUBJECT_TYPE_STATE_CONFLICT": HTTP_409_CONFLICT,
}


def _error(exc, request):
    return error_response(ErrorCode(exc.code), status_code=ERROR_STATUS[exc.code], request=request)


def _admin_type(subject_type_id):
    try:
        return SubjectType.objects.get(pk=subject_type_id)
    except SubjectType.DoesNotExist as exc:
        raise NotFound from exc


class PublicSubjectTypeListView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request):
        rows = SubjectType.objects.filter(status=SubjectType.Status.ACTIVE).order_by(
            "sort_order", "key", "id"
        )
        return Response(PublicSubjectTypeSerializer(rows, many=True).data)


class PublicSubjectFormSchemaView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_type_id):
        try:
            subject_type = SubjectType.objects.get(
                pk=subject_type_id, status=SubjectType.Status.ACTIVE
            )
        except SubjectType.DoesNotExist as exc:
            raise NotFound from exc
        return Response(PublicFormSchemaSerializer(subject_type).data)


class AdminSubjectTypeListView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "subject_types.list"
    required_permissions_by_method = {
        "GET": "subject_types.list",
        "POST": "subject_types.create",
    }

    def get(self, request):
        rows = SubjectType.objects.all()
        status_value = request.query_params.get("status", "")
        if status_value:
            rows = rows.filter(status=status_value)
        keyword = request.query_params.get("keyword", "").strip()
        if keyword:
            rows = rows.filter(Q(key__icontains=keyword) | Q(name__icontains=keyword))
        return Response(
            SubjectTypeSummarySerializer(rows.order_by("sort_order", "id"), many=True).data
        )

    @method_decorator(csrf_protect)
    def post(self, request):
        serializer = SubjectTypeCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = create_subject_type(request=request, data=dict(serializer.validated_data))
        except SubjectDomainError as exc:
            return _error(exc, request)
        return Response(SubjectTypeDetailSerializer(result).data, status=201)


class AdminSubjectTypeDetailView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "subject_types.view"
    required_permissions_by_method = {
        "GET": "subject_types.view",
        "PATCH": "subject_types.update",
    }

    def get(self, request, subject_type_id):
        return Response(SubjectTypeDetailSerializer(_admin_type(subject_type_id)).data)

    @method_decorator(csrf_protect)
    def patch(self, request, subject_type_id):
        serializer = SubjectTypeUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = update_subject_type(
                request=request,
                subject_type_id=subject_type_id,
                data=dict(serializer.validated_data),
            )
        except SubjectDomainError as exc:
            return _error(exc, request)
        return Response(SubjectTypeDetailSerializer(result).data)


class AdminSubjectTypeStatusView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "subject_types.disable"
    status_value = ""

    @method_decorator(csrf_protect)
    def post(self, request, subject_type_id):
        serializer = ExpectedSubjectTypeVersionsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = set_subject_type_status(
                request=request,
                subject_type_id=subject_type_id,
                status=self.status_value,
                data=dict(serializer.validated_data),
            )
        except SubjectDomainError as exc:
            return _error(exc, request)
        return Response(SubjectTypeDetailSerializer(result).data)


class AdminSubjectTypeEnableView(AdminSubjectTypeStatusView):
    status_value = SubjectType.Status.ACTIVE


class AdminSubjectTypeDisableView(AdminSubjectTypeStatusView):
    status_value = SubjectType.Status.INACTIVE


class AdminSubjectTypeFieldListView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "subject_fields.list"
    required_permissions_by_method = {
        "GET": "subject_fields.list",
        "POST": "subject_fields.create",
    }

    def get(self, request, subject_type_id):
        subject_type = _admin_type(subject_type_id)
        configs = (
            subject_type.field_configs.select_related("field_definition")
            .prefetch_related("options")
            .order_by("sort_order", "id")
        )
        return Response(SubjectTypeFieldConfigSerializer(configs, many=True).data)

    @method_decorator(csrf_protect)
    def post(self, request, subject_type_id):
        serializer = CustomFieldCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = create_custom_field(
                request=request,
                subject_type_id=subject_type_id,
                data=dict(serializer.validated_data),
            )
        except SubjectDomainError as exc:
            return _error(exc, request)
        return Response(SubjectTypeFieldConfigSerializer(result).data, status=201)


class AdminSubjectTypeFieldDetailView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "subject_fields.update"

    @method_decorator(csrf_protect)
    def patch(self, request, config_id):
        serializer = FieldConfigUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = update_field_config(
                request=request,
                config_id=config_id,
                data=dict(serializer.validated_data),
            )
        except SubjectDomainError as exc:
            return _error(exc, request)
        return Response(SubjectTypeFieldConfigSerializer(result).data)


class AdminSubjectFieldOptionListView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "subject_fields.update"

    @method_decorator(csrf_protect)
    def post(self, request, config_id):
        serializer = FieldOptionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = create_field_option(
                request=request,
                config_id=config_id,
                data=dict(serializer.validated_data),
            )
        except SubjectDomainError as exc:
            return _error(exc, request)
        return Response(SubjectFieldOptionSerializer(result).data, status=201)


class AdminSubjectFieldOptionDetailView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "subject_fields.update"

    @method_decorator(csrf_protect)
    def patch(self, request, option_id):
        serializer = FieldOptionUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = update_field_option(
                request=request,
                option_id=option_id,
                data=dict(serializer.validated_data),
            )
        except SubjectDomainError as exc:
            return _error(exc, request)
        return Response(SubjectFieldOptionSerializer(result).data)


class AdminSubjectTypeFieldOrderView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "subject_fields.update"

    @method_decorator(csrf_protect)
    def put(self, request, subject_type_id):
        serializer = FieldOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            subject_type = reorder_fields(
                request=request,
                subject_type_id=subject_type_id,
                data=dict(serializer.validated_data),
            )
        except SubjectDomainError as exc:
            return _error(exc, request)
        return Response(SubjectTypeDetailSerializer(subject_type).data)
