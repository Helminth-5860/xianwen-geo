from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_403_FORBIDDEN,
    HTTP_409_CONFLICT,
    HTTP_422_UNPROCESSABLE_ENTITY,
    HTTP_503_SERVICE_UNAVAILABLE,
)
from rest_framework.views import APIView

from apps.core.error_codes import ErrorCode
from apps.core.responses import error_response

from .permissions import IsAvailableAuthenticatedUser
from .profile_save_services import save_subject_profile
from .risk_services import SubjectRiskError
from .serializers import (
    SubjectCommitRequestSerializer,
    SubjectContextSerializer,
    SubjectCreateRequestSerializer,
    SubjectCurrentRequestSerializer,
    SubjectDetailSerializer,
    SubjectDraftUpdateRequestSerializer,
    SubjectSaveRequestSerializer,
    SubjectStatusRequestSerializer,
    SubjectSummarySerializer,
    SubjectVersionDetailSerializer,
    SubjectVersionSummarySerializer,
)
from .subject_services import (
    SubjectBusinessError,
    activate_subject,
    archive_subject,
    create_subject,
    set_current_subject,
    subject_context_for_user,
    subject_for_user_or_404,
    subjects_for_user,
    update_subject_draft,
)
from .version_services import (
    commit_subject_version,
    subject_version_for_user_or_404,
    subject_versions_for_user,
)

ERROR_STATUS = {
    "SUBJECT_SCHEMA_MISMATCH": HTTP_409_CONFLICT,
    "SUBJECT_FIELD_VALUES_INVALID": HTTP_422_UNPROCESSABLE_ENTITY,
    "SUBJECT_LIMIT_REACHED": HTTP_409_CONFLICT,
    "SUBJECT_LIMIT_RECONCILIATION_REQUIRED": HTTP_409_CONFLICT,
    "SUBJECT_ENTITLEMENT_INTEGRITY_ERROR": HTTP_503_SERVICE_UNAVAILABLE,
    "SUBJECT_VERSION_CONFLICT": HTTP_409_CONFLICT,
    "SUBJECT_CURRENT_VERSION_CONFLICT": HTTP_409_CONFLICT,
    "SUBJECT_STATE_CONFLICT": HTTP_409_CONFLICT,
    "SUBJECT_REQUIRED_FIELDS_INCOMPLETE": HTTP_422_UNPROCESSABLE_ENTITY,
    "SUBJECT_SEMANTICS_INVALID": HTTP_422_UNPROCESSABLE_ENTITY,
    "SUBJECT_PRODUCT_CONFIRMATION_INVALID": HTTP_422_UNPROCESSABLE_ENTITY,
    "SUBJECT_VERSION_NO_CHANGES": HTTP_409_CONFLICT,
    "SUBJECT_RISK_CONFIG_INTEGRITY_ERROR": HTTP_503_SERVICE_UNAVAILABLE,
    "PLAN_REQUIRED": HTTP_403_FORBIDDEN,
    "ACCOUNT_UNAVAILABLE": HTTP_403_FORBIDDEN,
}


def _error(exc, request):
    details = {}
    if getattr(exc, "field_key", ""):
        details["fields"] = {exc.field_key: ["\u5b57\u6bb5\u503c\u4e0d\u6b63\u786e"]}
    if getattr(exc, "field_keys", None):
        details["fields"] = {
            key: ["\u5fc5\u586b\u5b57\u6bb5\u4e0d\u80fd\u4e3a\u7a7a"] for key in exc.field_keys
        }
    return error_response(
        ErrorCode(exc.code),
        status_code=ERROR_STATUS[exc.code],
        request=request,
        details=details,
    )


def _detail(subject, *, current_subject_id=None):
    return SubjectDetailSerializer(
        subject,
        context={"current_subject_id": current_subject_id},
    ).data


class SubjectListCreateView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request):
        context = subject_context_for_user(request.user)
        current_id = context.current_subject_id if context else None
        rows = subjects_for_user(request.user)
        status_value = request.query_params.get("status")
        if status_value in {"draft", "active", "archived"}:
            rows = rows.filter(status=status_value)
        else:
            rows = rows.exclude(status="archived")
        return Response(
            {
                "subjects": SubjectSummarySerializer(
                    rows,
                    many=True,
                    context={"current_subject_id": current_id},
                ).data,
                "context": (
                    SubjectContextSerializer(context).data
                    if context
                    else {"current_subject_id": None, "version": 0}
                ),
            }
        )

    @method_decorator(csrf_protect)
    def post(self, request):
        serializer = SubjectCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            subject = create_subject(
                user_id=request.user.pk,
                subject_type_id=serializer.validated_data["subject_type_id"],
                expected_schema_version=serializer.validated_data["expected_schema_version"],
                initial_values=dict(serializer.validated_data["initial_values"]),
                request_id=request.request_id,
            )
        except SubjectBusinessError as exc:
            return _error(exc, request)
        context = subject_context_for_user(request.user)
        return Response(
            _detail(
                subject,
                current_subject_id=context.current_subject_id if context else None,
            ),
            status=201,
        )


class SubjectDetailView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        subject = subject_for_user_or_404(user=request.user, subject_id=subject_id)
        context = subject_context_for_user(request.user)
        return Response(
            _detail(
                subject,
                current_subject_id=context.current_subject_id if context else None,
            )
        )

    @method_decorator(csrf_protect)
    def put(self, request, subject_id):
        serializer = SubjectSaveRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            subject, version, version_created = save_subject_profile(
                user_id=request.user.pk,
                subject_id=subject_id,
                expected_version=serializer.validated_data["expected_version"],
                values=dict(serializer.validated_data["values"]),
                profile_values=(
                    dict(serializer.validated_data["profile_values"])
                    if "profile_values" in serializer.validated_data
                    else None
                ),
                request_id=request.request_id,
            )
        except (SubjectBusinessError, SubjectRiskError) as exc:
            return _error(exc, request)
        context = subject_context_for_user(request.user)
        return Response(
            {
                "subject": _detail(
                    subject,
                    current_subject_id=context.current_subject_id if context else None,
                ),
                "version": SubjectVersionDetailSerializer(version).data,
                "version_created": version_created,
            }
        )


class SubjectDraftView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def patch(self, request, subject_id):
        serializer = SubjectDraftUpdateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            subject = update_subject_draft(
                user_id=request.user.pk,
                subject_id=subject_id,
                expected_version=serializer.validated_data["expected_version"],
                values=dict(serializer.validated_data["values"]),
                profile_values=(
                    dict(serializer.validated_data["profile_values"])
                    if "profile_values" in serializer.validated_data
                    else None
                ),
            )
        except SubjectBusinessError as exc:
            return _error(exc, request)
        context = subject_context_for_user(request.user)
        return Response(
            _detail(
                subject,
                current_subject_id=context.current_subject_id if context else None,
            )
        )


class SubjectStatusView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]
    operation = ""

    @method_decorator(csrf_protect)
    def post(self, request, subject_id):
        serializer = SubjectStatusRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            service = activate_subject if self.operation == "activate" else archive_subject
            subject = service(
                user_id=request.user.pk,
                subject_id=subject_id,
                expected_version=serializer.validated_data["expected_version"],
                request_id=request.request_id,
            )
        except SubjectBusinessError as exc:
            return _error(exc, request)
        context = subject_context_for_user(request.user)
        return Response(
            _detail(
                subject,
                current_subject_id=context.current_subject_id if context else None,
            )
        )


class SubjectActivateView(SubjectStatusView):
    operation = "activate"


class SubjectArchiveView(SubjectStatusView):
    operation = "archive"


class SubjectCurrentView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def put(self, request):
        serializer = SubjectCurrentRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            context = set_current_subject(
                user_id=request.user.pk,
                subject_id=serializer.validated_data["subject_id"],
                expected_version=serializer.validated_data["expected_version"],
                request_id=request.request_id,
            )
        except SubjectBusinessError as exc:
            return _error(exc, request)
        return Response(SubjectContextSerializer(context).data)


class SubjectCommitView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    @method_decorator(csrf_protect)
    def post(self, request, subject_id):
        serializer = SubjectCommitRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            subject, version = commit_subject_version(
                user_id=request.user.pk,
                subject_id=subject_id,
                expected_version=serializer.validated_data["expected_version"],
                product_confirmations=list(serializer.validated_data["products"]),
                request_id=request.request_id,
            )
        except (SubjectBusinessError, SubjectRiskError) as exc:
            return _error(exc, request)
        context = subject_context_for_user(request.user)
        return Response(
            {
                "subject": _detail(
                    subject,
                    current_subject_id=context.current_subject_id if context else None,
                ),
                "version": SubjectVersionDetailSerializer(version).data,
            },
            status=201,
        )


class SubjectVersionListView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id):
        versions = subject_versions_for_user(user=request.user, subject_id=subject_id)
        return Response({"versions": SubjectVersionSummarySerializer(versions, many=True).data})


class SubjectVersionDetailView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, subject_id, version_id):
        version = subject_version_for_user_or_404(
            user=request.user,
            subject_id=subject_id,
            version_id=version_id,
        )
        return Response(SubjectVersionDetailSerializer(version).data)
