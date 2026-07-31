from django.core.checks import Warning, register
from django.db import OperationalError, ProgrammingError
from django.db.models import Q

from apps.users.models import User

from .models import AdminProfile, AdminRole


@register()
def admin_profile_invariants(app_configs, **kwargs):
    warnings: list[Warning] = []
    try:
        missing_profiles = User.objects.filter(
            Q(is_staff=True) | Q(is_superuser=True), admin_profile__isnull=True
        ).exists()
        invalid_superusers = (
            AdminProfile.objects.filter(user__is_superuser=True)
            .exclude(
                admin_status=AdminProfile.Status.ACTIVE,
                role__isnull=True,
                user__is_staff=True,
                user__is_active=True,
            )
            .exists()
        )
        invalid_ordinary_admins = (
            AdminProfile.objects.filter(
                user__is_superuser=False,
                admin_status=AdminProfile.Status.ACTIVE,
            )
            .filter(
                Q(role__isnull=True)
                | ~Q(role__status=AdminRole.Status.ACTIVE)
                | Q(user__is_staff=False)
                | Q(user__is_active=False)
            )
            .exists()
        )
    except (OperationalError, ProgrammingError):
        return warnings
    if missing_profiles:
        warnings.append(
            Warning(
                "存在缺少 AdminProfile 的 staff/superuser，后台权限将默认拒绝。",
                id="admin_rbac.W001",
            )
        )
    if invalid_ordinary_admins:
        warnings.append(
            Warning(
                "存在不满足角色、状态或 User 投影的启用普通管理员，后台权限将默认拒绝。",
                id="admin_rbac.W002",
            )
        )
    if invalid_superusers:
        warnings.append(
            Warning(
                "存在不满足 active、role=null 投影的超级管理员，后台权限将默认拒绝。",
                id="admin_rbac.W003",
            )
        )
    return warnings
