from django.contrib.auth import login
from django.db import transaction
from rest_framework.authentication import SessionAuthentication

from .models import User

SESSION_VERSION_KEY = "_xianwen_user_session_version"


class AccountUnavailable(Exception):
    pass


class ApiSessionAuthentication(SessionAuthentication):
    def authenticate_header(self, request) -> str:
        return "Session"


@transaction.atomic
def start_browser_session(request, user_id) -> User:
    user = User.objects.select_for_update().get(pk=user_id)
    if not user.is_active or user.account_status not in User.ACTIVE_ACCOUNT_STATUSES:
        raise AccountUnavailable
    login(
        request,
        user,
        backend="django.contrib.auth.backends.ModelBackend",
    )
    request.session[SESSION_VERSION_KEY] = user.session_version
    request.session.set_expiry(0)
    return user
