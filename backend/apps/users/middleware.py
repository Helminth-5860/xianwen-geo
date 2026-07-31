from django.contrib.auth import logout

from .authentication import SESSION_VERSION_KEY


class SessionVersionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated:
            session_version = request.session.get(SESSION_VERSION_KEY)
            valid_version = (
                isinstance(session_version, int)
                and not isinstance(session_version, bool)
                and session_version > 0
                and session_version == user.session_version
            )
            if not valid_version:
                logout(request)
            else:
                from apps.admin_rbac.models import AdminProfile
                from apps.admin_rbac.permissions import resolve_admin_context

                is_admin_identity = (
                    AdminProfile.objects.filter(user=user).exists()
                    or user.is_staff
                    or user.is_superuser
                )
                if is_admin_identity and resolve_admin_context(user) is None:
                    logout(request)
        return self.get_response(request)
