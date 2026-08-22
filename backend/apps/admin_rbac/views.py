from math import ceil

from django.db import IntegrityError
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.status import HTTP_201_CREATED, HTTP_202_ACCEPTED, HTTP_409_CONFLICT
from rest_framework.views import APIView

from apps.core.responses import error_response

from .models import AdminPermission, AdminProfile, AdminRole, CustomerAssignment
from .permissions import HasAdminPermission
from .risk_services import RiskError, perform_risk_action
from .risk_views import risk_error_response
from .scopes import scoped_customer_or_404
from .security import AdminReauthFailed, AdminReauthRateLimited, AdminSecurityUnavailable
from .serializers import (
    AdminCreateSerializer,
    AdminProfileSerializer,
    AdminRoleChangeSerializer,
    AdminUpdateSerializer,
    AssignmentSerializer,
    AssignmentUpdateSerializer,
    PermissionSerializer,
    RoleCreateSerializer,
    RolePermissionsReplaceSerializer,
    RoleSerializer,
    RoleUpdateSerializer,
    VersionSerializer,
)
from .services import (
    AdminHasAssignedCustomers,
    AdminStateConflict,
    AdminVersionConflict,
    AssignmentVersionConflict,
    LastSuperuserProtected,
    RoleInUse,
    RoleVersionConflict,
    change_admin_status,
    create_admin,
    create_role,
    update_admin,
    update_role,
)


def _conflict(exc, request):
    from apps.core.error_codes import ErrorCode

    return error_response(
        ErrorCode(exc.code),
        status_code=HTTP_409_CONFLICT,
        request=request,
    )


def _page(queryset, serializer, request):
    page = max(int(request.query_params.get("page", 1)), 1)
    page_size = min(max(int(request.query_params.get("page_size", 20)), 1), 100)
    count = queryset.count()
    offset = (page - 1) * page_size
    return {
        "results": serializer(queryset[offset : offset + page_size], many=True).data,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "count": count,
            "total_pages": ceil(count / page_size) if count else 0,
        },
    }


class AdminMeView(APIView):
    required_permission = "admin.dashboard.view"
    permission_classes = [HasAdminPermission]

    def get(self, request):
        context = request.admin_context
        profile_data = AdminProfileSerializer(context.profile).data
        return Response(
            {
                **profile_data,
                "admin_version": profile_data.pop("version"),
                "data_scope": context.profile.role.data_scope
                if context.profile.role
                else AdminRole.DataScope.ALL,
                "permission_keys": sorted(context.permission_keys),
                "menu_keys": sorted(context.menu_keys),
            }
        )


@method_decorator(csrf_protect, name="dispatch")
class AdminListCreateView(APIView):
    required_permission = "admins.list"
    permission_classes = [HasAdminPermission]
    step_up_methods = {"POST"}

    def get(self, request):
        queryset = AdminProfile.objects.select_related("user", "role").order_by("created_at", "id")
        return Response(_page(queryset, AdminProfileSerializer, request))

    @method_decorator(csrf_protect)
    def post(self, request):
        self.required_permission = "admins.create"
        self.check_permissions(request)
        serializer = AdminCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            profile = create_admin(
                actor_id=request.user.pk,
                request_id=request.request_id,
                **serializer.validated_data,
            )
        except IntegrityError:
            from apps.core.error_codes import ErrorCode

            return error_response(
                ErrorCode.ACCOUNT_ALREADY_EXISTS, status_code=HTTP_409_CONFLICT, request=request
            )
        return Response(AdminProfileSerializer(profile).data, status=HTTP_201_CREATED)


@method_decorator(csrf_protect, name="dispatch")
class AdminDetailView(APIView):
    required_permission = "admins.view"
    permission_classes = [HasAdminPermission]
    step_up_methods = {"PATCH"}

    def _get(self, profile_id):
        try:
            return AdminProfile.objects.select_related("user", "role").get(pk=profile_id)
        except AdminProfile.DoesNotExist as exc:
            raise NotFound from exc

    def get(self, request, profile_id):
        return Response(AdminProfileSerializer(self._get(profile_id)).data)

    @method_decorator(csrf_protect)
    def patch(self, request, profile_id):
        self.required_permission = "admins.update"
        self.check_permissions(request)
        serializer = AdminUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            profile = update_admin(
                actor_id=request.user.pk,
                profile_id=profile_id,
                request_id=request.request_id,
                **serializer.validated_data,
                role_id=None,
            )
        except AdminVersionConflict as exc:
            return _conflict(exc, request)
        return Response(AdminProfileSerializer(profile).data)


@method_decorator(csrf_protect, name="dispatch")
class AdminRoleChangeView(APIView):
    required_permission = "admins.update"
    permission_classes = [HasAdminPermission]

    def post(self, request, profile_id):
        serializer = AdminRoleChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            result = perform_risk_action(
                request=request,
                action_key="admin.role.change",
                target_id=profile_id,
                target_version=data["expected_version"],
                raw_payload={"role_id": data["role_id"]},
                confirmed=data["confirmed"],
                current_password=data["current_password"],
            )
        except (
            RiskError,
            AdminReauthFailed,
            AdminReauthRateLimited,
            AdminSecurityUnavailable,
        ) as exc:
            return risk_error_response(exc, request)
        except AdminVersionConflict as exc:
            return _conflict(exc, request)
        if result.approval_required:
            return Response(result.data, status=HTTP_202_ACCEPTED)
        profile = AdminProfile.objects.select_related("user", "role").get(pk=profile_id)
        return Response(AdminProfileSerializer(profile).data)


@method_decorator(csrf_protect, name="dispatch")
class AdminStatusView(APIView):
    required_permission = "admins.disable"
    permission_classes = [HasAdminPermission]
    requires_step_up = True
    action = ""

    @method_decorator(csrf_protect)
    def post(self, request, profile_id):
        serializer = VersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            data = serializer.validated_data
            if self.action in {"disable", "lock"}:
                result = perform_risk_action(
                    request=request,
                    action_key=f"admin.{self.action}",
                    target_id=profile_id,
                    target_version=data["expected_version"],
                    raw_payload={},
                    confirmed=data["confirmed"],
                    current_password=data["current_password"],
                )
                if result.approval_required:
                    return Response(result.data, status=HTTP_202_ACCEPTED)
                profile = AdminProfile.objects.select_related("user", "role").get(pk=profile_id)
            else:
                profile = change_admin_status(
                    actor_id=request.user.pk,
                    profile_id=profile_id,
                    action=self.action,
                    expected_version=data["expected_version"],
                    request_id=request.request_id,
                )
        except (
            RiskError,
            AdminReauthFailed,
            AdminReauthRateLimited,
            AdminSecurityUnavailable,
        ) as exc:
            return risk_error_response(exc, request)
        except (
            AdminStateConflict,
            AdminVersionConflict,
            AdminHasAssignedCustomers,
            LastSuperuserProtected,
        ) as exc:
            return _conflict(exc, request)
        return Response(AdminProfileSerializer(profile).data)


@method_decorator(csrf_protect, name="dispatch")
class RoleListCreateView(APIView):
    required_permission = "roles.list"
    permission_classes = [HasAdminPermission]
    step_up_methods = {"POST"}

    def get(self, request):
        return Response(_page(AdminRole.objects.all(), RoleSerializer, request))

    @method_decorator(csrf_protect)
    def post(self, request):
        self.required_permission = "roles.create"
        self.check_permissions(request)
        serializer = RoleCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        role = create_role(
            actor_id=request.user.pk, request_id=request.request_id, **serializer.validated_data
        )
        return Response(RoleSerializer(role).data, status=HTTP_201_CREATED)


@method_decorator(csrf_protect, name="dispatch")
class RoleDetailView(APIView):
    required_permission = "roles.view"
    permission_classes = [HasAdminPermission]
    step_up_methods = {"PATCH"}

    def _get(self, role_id):
        try:
            return AdminRole.objects.get(pk=role_id)
        except AdminRole.DoesNotExist as exc:
            raise NotFound from exc

    def get(self, request, role_id):
        return Response(RoleSerializer(self._get(role_id)).data)

    @method_decorator(csrf_protect)
    def patch(self, request, role_id):
        self.required_permission = "roles.update"
        self.check_permissions(request)
        serializer = RoleUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            data = serializer.validated_data
            role = update_role(
                actor_id=request.user.pk,
                role_id=role_id,
                expected_version=data["expected_version"],
                name=data.get("name"),
                description=data.get("description"),
                data_scope=None,
                permission_keys=None,
                request_id=request.request_id,
            )
        except RoleVersionConflict as exc:
            return _conflict(exc, request)
        return Response(RoleSerializer(role).data)


@method_decorator(csrf_protect, name="dispatch")
class RolePermissionsView(APIView):
    required_permission = "roles.update"
    permission_classes = [HasAdminPermission]

    def put(self, request, role_id):
        serializer = RolePermissionsReplaceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            result = perform_risk_action(
                request=request,
                action_key="role.permissions.replace",
                target_id=role_id,
                target_version=data["expected_version"],
                raw_payload={"permission_keys": data["permission_keys"]},
                confirmed=data["confirmed"],
                current_password=data["current_password"],
            )
        except (
            RiskError,
            AdminReauthFailed,
            AdminReauthRateLimited,
            AdminSecurityUnavailable,
        ) as exc:
            return risk_error_response(exc, request)
        except RoleVersionConflict as exc:
            return _conflict(exc, request)
        if result.approval_required:
            return Response(result.data, status=HTTP_202_ACCEPTED)
        return Response(RoleSerializer(AdminRole.objects.get(pk=role_id)).data)


@method_decorator(csrf_protect, name="dispatch")
class RoleDisableView(APIView):
    required_permission = "roles.disable"
    permission_classes = [HasAdminPermission]

    @method_decorator(csrf_protect)
    def post(self, request, role_id):
        serializer = VersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            result = perform_risk_action(
                request=request,
                action_key="role.disable",
                target_id=role_id,
                target_version=data["expected_version"],
                raw_payload={},
                confirmed=data["confirmed"],
                current_password=data["current_password"],
            )
        except (
            RiskError,
            AdminReauthFailed,
            AdminReauthRateLimited,
            AdminSecurityUnavailable,
        ) as exc:
            return risk_error_response(exc, request)
        except (RoleVersionConflict, RoleInUse) as exc:
            return _conflict(exc, request)
        if result.approval_required:
            return Response(result.data, status=HTTP_202_ACCEPTED)
        return Response(RoleSerializer(AdminRole.objects.get(pk=role_id)).data)


class PermissionListView(APIView):
    required_permission = "roles.list"
    permission_classes = [HasAdminPermission]

    def get(self, request):
        return Response(PermissionSerializer(AdminPermission.objects.all(), many=True).data)


@method_decorator(csrf_protect, name="dispatch")
class CustomerAssignmentView(APIView):
    required_permission = "users.assign"
    permission_classes = [HasAdminPermission]

    def get(self, request, customer_id):
        customer = scoped_customer_or_404(request.user, request.admin_context, customer_id)
        assignment = (
            CustomerAssignment.objects.select_related("owner_admin__user")
            .filter(customer=customer)
            .first()
        )
        if assignment is None:
            return Response(
                {
                    "id": None,
                    "customer_id": str(customer.pk),
                    "owner_admin_id": None,
                    "owner_nickname": None,
                    "owner_phone_masked": "",
                    "version": 0,
                    "assigned_at": None,
                }
            )
        return Response(AssignmentSerializer(assignment).data)

    @method_decorator(csrf_protect)
    def put(self, request, customer_id):
        serializer = AssignmentUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            result = perform_risk_action(
                request=request,
                action_key="customer.assignment.change",
                target_id=customer_id,
                target_version=data["expected_version"],
                raw_payload={
                    "owner_admin_id": data["owner_admin_id"],
                    "reason": data.get("reason", ""),
                },
                confirmed=data["confirmed"],
                current_password=data["current_password"],
            )
        except (
            RiskError,
            AdminReauthFailed,
            AdminReauthRateLimited,
            AdminSecurityUnavailable,
        ) as exc:
            return risk_error_response(exc, request)
        except AssignmentVersionConflict as exc:
            return _conflict(exc, request)
        if result.approval_required:
            return Response(result.data, status=HTTP_202_ACCEPTED)
        assignment = CustomerAssignment.objects.get(customer_id=customer_id)
        return Response(AssignmentSerializer(assignment).data)


def status_view(action):
    return type(f"Admin{action.title()}View", (AdminStatusView,), {"action": action})
