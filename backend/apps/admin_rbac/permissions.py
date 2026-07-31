from dataclasses import dataclass

from rest_framework.permissions import BasePermission

from .catalog import CATALOG_BY_KEY
from .models import AdminPermission, AdminProfile, AdminRole


@dataclass(frozen=True)
class AdminContext:
    profile: AdminProfile
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
    if user.is_superuser:
        if not user.is_staff or profile.role_id is not None:
            return None
        active = AdminPermission.objects.filter(status=AdminPermission.Status.ACTIVE)
    else:
        role = profile.role
        if not user.is_staff or role is None or role.status != AdminRole.Status.ACTIVE:
            return None
        active = AdminPermission.objects.filter(
            status=AdminPermission.Status.ACTIVE,
            role_links__role=role,
            superuser_only=False,
        )
    keys = frozenset(active.values_list("key", flat=True))
    menu_keys = frozenset(
        active.filter(permission_type=AdminPermission.PermissionType.MENU).values_list(
            "key", flat=True
        )
    )
    return AdminContext(profile=profile, permission_keys=keys, menu_keys=menu_keys)


class HasAdminPermission(BasePermission):
    message = "没有权限执行此操作"

    def has_permission(self, request, view) -> bool:
        required = getattr(view, "required_permission", None)
        if not required or required not in CATALOG_BY_KEY:
            return False
        context = resolve_admin_context(request.user)
        if context is None:
            return False
        request.admin_context = context
        return request.user.is_superuser or required in context.permission_keys
