from rest_framework.permissions import BasePermission

from apps.users.models import User


class IsAvailableAuthenticatedUser(BasePermission):
    message = "账号当前不可用"

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(
            user.is_authenticated
            and user.is_active
            and user.account_status
            in {User.AccountStatus.ACTIVE, User.AccountStatus.CANCEL_PENDING}
        )
