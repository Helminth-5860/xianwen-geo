from dataclasses import dataclass

from rest_framework.permissions import BasePermission

from apps.users.commercial import CommercialIdentity, commercial_identity

from .catalog import CATALOG_BY_KEY
from .commercial_policy import ADMIN_BASELINE_PERMISSIONS
from .models import AdminPermission, AdminProfile, AdminRole


def _step_up_required(view, method: str) -> bool:
    return bool(
        getattr(view, "requires_step_up", False) or method in getattr(view, "step_up_methods", ())
    )


@dataclass(frozen=True)
class AdminContext:
    profile: AdminProfile
    identity: CommercialIdentity
    tenant_id: object | None
    permission_keys: frozenset[str]
    menu_keys: frozenset[str]


def resolve_admin_context(user) -> AdminContext | None:
    if not user.is_authenticated or not user.is_active:
        return None
    try:
        profile = AdminProfile.objects.select_related("role").get(user=user)
    except AdminProfile.DoesNotExist:
        return None
    if profile.admin_status != AdminProfile.Status.ACTIVE:
        return None
    identity = commercial_identity(user)
    if identity == CommercialIdentity.SUPER_ADMIN:
        if not user.is_staff or profile.role_id is not None:
            return None
        active = AdminPermission.objects.filter(status=AdminPermission.Status.ACTIVE)
    elif identity == CommercialIdentity.ADMIN:
        role = profile.role
        if not user.is_staff or role is None or role.status != AdminRole.Status.ACTIVE:
            return None
        explicit = AdminPermission.objects.filter(
            status=AdminPermission.Status.ACTIVE,
            role_links__role=role,
            superuser_only=False,
        )
        baseline = AdminPermission.objects.filter(
            status=AdminPermission.Status.ACTIVE,
            key__in=ADMIN_BASELINE_PERMISSIONS,
            superuser_only=False,
        )
        active = (explicit | baseline).distinct()
    else:
        return None
    keys = frozenset(active.values_list("key", flat=True))
    menu_keys = frozenset(
        active.filter(permission_type=AdminPermission.PermissionType.MENU).values_list(
            "key", flat=True
        )
    )
    return AdminContext(
        profile=profile,
        identity=identity,
        tenant_id=user.tenant_id,
        permission_keys=keys,
        menu_keys=menu_keys,
    )


class HasAdminPermission(BasePermission):
    message = "没有权限执行此操作"

    def has_permission(self, request, view) -> bool:
        required_by_method = getattr(view, "required_permissions_by_method", {})
        required = required_by_method.get(
            request.method, getattr(view, "required_permission", None)
        )
        if not required or required not in CATALOG_BY_KEY:
            return False
        from .security import validate_admin_session

        security_snapshot = validate_admin_session(request)
        if security_snapshot is None:
            return False
        context = resolve_admin_context(request.user)
        if context is None:
            return False
        authorized = request.user.is_superuser or required in context.permission_keys
        if not authorized:
            return False
        request.admin_security_snapshot = security_snapshot
        request.admin_context = context
        if _step_up_required(view, request.method):
            from .security import require_admin_step_up

            require_admin_step_up(request, security_snapshot)
        return True


class HasAdminSession(BasePermission):
    message = "需要完成管理员安全认证"

    def has_permission(self, request, view) -> bool:
        from .security import validate_admin_session

        snapshot = validate_admin_session(request)
        if snapshot is None:
            return False
        request.admin_security_snapshot = snapshot
        context = resolve_admin_context(request.user)
        if context is None:
            return False
        request.admin_context = context
        if _step_up_required(view, request.method):
            from .security import require_admin_step_up

            require_admin_step_up(request, snapshot)
        return True


class HasSuperuserAdminSession(HasAdminSession):
    message = "只有超级管理员可以执行此操作"

    def has_permission(self, request, view) -> bool:
        return super().has_permission(request, view) and request.user.is_superuser
