from rest_framework.permissions import BasePermission

from .models import User


class IsActiveStaff(BasePermission):
    message = "没有权限执行此操作"

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(user.is_authenticated and user.is_active and user.is_staff)


class ApprovedAndActive(BasePermission):
    message = "账号当前不可用"

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(
            user.is_authenticated
            and user.is_active
            and user.approval_status == User.ApprovalStatus.APPROVED
            and user.account_status == User.AccountStatus.ACTIVE
        )
