from django.db.models import Q
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.status import HTTP_201_CREATED, HTTP_409_CONFLICT, HTTP_422_UNPROCESSABLE_ENTITY
from rest_framework.views import APIView

from apps.admin_rbac.permissions import HasAdminPermission
from apps.core.error_codes import ErrorCode
from apps.core.responses import error_response
from apps.subjects.models import SubjectType
from apps.subjects.permissions import IsAvailableAuthenticatedUser

from .exceptions import QuestionCatalogError
from .models import QuestionCategory, QuestionTag
from .serializers import (
    ExpectedQuestionCatalogVersionSerializer,
    PublicQuestionCatalogQuerySerializer,
    PublicQuestionCategorySerializer,
    PublicQuestionTagSerializer,
    QuestionCatalogQuerySerializer,
    QuestionCategoryCreateSerializer,
    QuestionCategorySerializer,
    QuestionCategoryUpdateSerializer,
    QuestionTagCreateSerializer,
    QuestionTagSerializer,
    QuestionTagUpdateSerializer,
)
from .services import (
    create_question_category,
    create_question_tag,
    set_question_category_status,
    set_question_tag_status,
    update_question_category,
    update_question_tag,
)

ERROR_STATUS = {
    "QUESTION_CATALOG_VERSION_CONFLICT": HTTP_409_CONFLICT,
    "QUESTION_CATALOG_DUPLICATE": HTTP_409_CONFLICT,
    "QUESTION_CATALOG_STATE_CONFLICT": HTTP_409_CONFLICT,
    "QUESTION_CATALOG_VALUES_INVALID": HTTP_422_UNPROCESSABLE_ENTITY,
}


def _error(exc, request):
    return error_response(
        ErrorCode(exc.code),
        status_code=ERROR_STATUS.get(exc.code, HTTP_409_CONFLICT),
        request=request,
    )


def _no_store(response):
    response["Cache-Control"] = "no-store"
    return response


def _category_or_404(category_id):
    try:
        return QuestionCategory.objects.get(pk=category_id)
    except QuestionCategory.DoesNotExist as exc:
        raise NotFound from exc


def _tag_or_404(tag_id):
    try:
        return QuestionTag.objects.get(pk=tag_id)
    except QuestionTag.DoesNotExist as exc:
        raise NotFound from exc


def _filter_applicability(rows, subject_type_id, *, relation):
    if subject_type_id is None:
        return rows
    if not SubjectType.objects.filter(
        pk=subject_type_id, status=SubjectType.Status.ACTIVE
    ).exists():
        raise NotFound
    return rows.filter(
        Q(**{f"{relation}__isnull": True}) | Q(**{f"{relation}__subject_type_id": subject_type_id})
    ).distinct()


class PublicQuestionCatalogView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request):
        query = PublicQuestionCatalogQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        subject_type_id = query.validated_data.get("subject_type_id")
        categories = _filter_applicability(
            QuestionCategory.objects.filter(status=QuestionCategory.Status.ACTIVE),
            subject_type_id,
            relation="subject_type_links",
        ).order_by("sort_order", "key", "id")
        tags = _filter_applicability(
            QuestionTag.objects.filter(status=QuestionTag.Status.ACTIVE),
            subject_type_id,
            relation="subject_type_links",
        ).order_by("sort_order", "key", "id")
        return _no_store(
            Response(
                {
                    "categories": PublicQuestionCategorySerializer(categories, many=True).data,
                    "tags": PublicQuestionTagSerializer(tags, many=True).data,
                }
            )
        )


class AdminQuestionCategoryListView(APIView):
    permission_classes = [HasAdminPermission]
    required_permissions_by_method = {
        "GET": "question_categories.list",
        "POST": "question_categories.create",
    }

    def get(self, request):
        query = QuestionCatalogQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        rows = QuestionCategory.objects.all()
        status = query.validated_data["status"]
        if status:
            rows = rows.filter(status=status)
        keyword = query.validated_data["keyword"].strip()
        if keyword:
            rows = rows.filter(Q(key__icontains=keyword) | Q(name__icontains=keyword))
        rows = _filter_applicability(
            rows, query.validated_data.get("subject_type_id"), relation="subject_type_links"
        )
        return _no_store(
            Response(
                QuestionCategorySerializer(rows.order_by("sort_order", "key", "id"), many=True).data
            )
        )

    @method_decorator(csrf_protect)
    def post(self, request):
        serializer = QuestionCategoryCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            row = create_question_category(request=request, data=dict(serializer.validated_data))
        except QuestionCatalogError as exc:
            return _error(exc, request)
        return _no_store(Response(QuestionCategorySerializer(row).data, status=HTTP_201_CREATED))


class AdminQuestionCategoryDetailView(APIView):
    permission_classes = [HasAdminPermission]
    required_permissions_by_method = {
        "GET": "question_categories.list",
        "PATCH": "question_categories.update",
    }

    def get(self, request, category_id):
        return _no_store(Response(QuestionCategorySerializer(_category_or_404(category_id)).data))

    @method_decorator(csrf_protect)
    def patch(self, request, category_id):
        serializer = QuestionCategoryUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            row = update_question_category(
                request=request, category_id=category_id, data=dict(serializer.validated_data)
            )
        except QuestionCategory.DoesNotExist as exc:
            raise NotFound from exc
        except QuestionCatalogError as exc:
            return _error(exc, request)
        return _no_store(Response(QuestionCategorySerializer(row).data))


class AdminQuestionCategoryStatusView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "question_categories.disable"
    status_value = ""

    @method_decorator(csrf_protect)
    def post(self, request, category_id):
        serializer = ExpectedQuestionCatalogVersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            row = set_question_category_status(
                request=request,
                category_id=category_id,
                status=self.status_value,
                expected_version=serializer.validated_data["expected_version"],
            )
        except QuestionCategory.DoesNotExist as exc:
            raise NotFound from exc
        except QuestionCatalogError as exc:
            return _error(exc, request)
        return _no_store(Response(QuestionCategorySerializer(row).data))


class AdminQuestionCategoryEnableView(AdminQuestionCategoryStatusView):
    status_value = QuestionCategory.Status.ACTIVE


class AdminQuestionCategoryDisableView(AdminQuestionCategoryStatusView):
    status_value = QuestionCategory.Status.INACTIVE


class AdminQuestionTagListView(APIView):
    permission_classes = [HasAdminPermission]
    required_permissions_by_method = {
        "GET": "question_tags.list",
        "POST": "question_tags.create",
    }

    def get(self, request):
        query = QuestionCatalogQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        rows = QuestionTag.objects.all()
        status = query.validated_data["status"]
        if status:
            rows = rows.filter(status=status)
        keyword = query.validated_data["keyword"].strip()
        if keyword:
            rows = rows.filter(Q(key__icontains=keyword) | Q(name__icontains=keyword))
        rows = _filter_applicability(
            rows, query.validated_data.get("subject_type_id"), relation="subject_type_links"
        )
        return _no_store(
            Response(
                QuestionTagSerializer(rows.order_by("sort_order", "key", "id"), many=True).data
            )
        )

    @method_decorator(csrf_protect)
    def post(self, request):
        serializer = QuestionTagCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            row = create_question_tag(request=request, data=dict(serializer.validated_data))
        except QuestionCatalogError as exc:
            return _error(exc, request)
        return _no_store(Response(QuestionTagSerializer(row).data, status=HTTP_201_CREATED))


class AdminQuestionTagDetailView(APIView):
    permission_classes = [HasAdminPermission]
    required_permissions_by_method = {
        "GET": "question_tags.list",
        "PATCH": "question_tags.update",
    }

    def get(self, request, tag_id):
        return _no_store(Response(QuestionTagSerializer(_tag_or_404(tag_id)).data))

    @method_decorator(csrf_protect)
    def patch(self, request, tag_id):
        serializer = QuestionTagUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            row = update_question_tag(
                request=request, tag_id=tag_id, data=dict(serializer.validated_data)
            )
        except QuestionTag.DoesNotExist as exc:
            raise NotFound from exc
        except QuestionCatalogError as exc:
            return _error(exc, request)
        return _no_store(Response(QuestionTagSerializer(row).data))


class AdminQuestionTagStatusView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "question_tags.disable"
    status_value = ""

    @method_decorator(csrf_protect)
    def post(self, request, tag_id):
        serializer = ExpectedQuestionCatalogVersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            row = set_question_tag_status(
                request=request,
                tag_id=tag_id,
                status=self.status_value,
                expected_version=serializer.validated_data["expected_version"],
            )
        except QuestionTag.DoesNotExist as exc:
            raise NotFound from exc
        except QuestionCatalogError as exc:
            return _error(exc, request)
        return _no_store(Response(QuestionTagSerializer(row).data))


class AdminQuestionTagEnableView(AdminQuestionTagStatusView):
    status_value = QuestionTag.Status.ACTIVE


class AdminQuestionTagDisableView(AdminQuestionTagStatusView):
    status_value = QuestionTag.Status.INACTIVE
