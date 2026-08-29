from rest_framework.permissions import BasePermission

from .models import User


class IsActiveStaff(BasePermission):
    message = "没有权限执行此操作"

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(user.is_authenticated and user.is_active and user.is_staff)


class ActiveAccount(BasePermission):
    message = "账号当前不可用"

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(
            user.is_authenticated
            and user.is_active
            and user.account_status == User.AccountStatus.ACTIVE
        )


class IsOrdinaryAvailableUser(BasePermission):
    message = "此设置仅适用于普通用户账号。"

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not (
            user.is_authenticated
            and user.is_active
            and user.account_status in User.ACTIVE_ACCOUNT_STATUSES
        ):
            return False

        from apps.admin_rbac.security import admin_identity

        return not admin_identity(user)
