from types import SimpleNamespace

from apps.admin_rbac.models import AdminProfile, SuperuserSecurityPolicy
from apps.admin_rbac.security import (
    ADMIN_AUTH_FACTORS_KEY,
    ADMIN_AUTH_TIME_KEY,
    ADMIN_AUTHENTICATED_KEY,
    ADMIN_IP_FINGERPRINT_KEY,
    ADMIN_POLICY_VERSION_KEY,
    ADMIN_PROFILE_ID_KEY,
    ADMIN_PROFILE_VERSION_KEY,
    ADMIN_ROLE_ID_KEY,
    ADMIN_ROLE_SECURITY_VERSION_KEY,
    ADMIN_ROLE_VERSION_KEY,
    admin_ip_fingerprint,
    grant_admin_step_up,
    security_snapshot,
)
from apps.users.authentication import SESSION_VERSION_KEY


def authenticate_admin_client(client, user, ip_address="127.0.0.1", *, step_up=True):
    profile = AdminProfile.objects.select_related("role").get(user=user)
    policy = None
    if user.is_superuser:
        policy, _ = SuperuserSecurityPolicy.objects.get_or_create(user=user)
    role = profile.role
    session = client.session
    session[SESSION_VERSION_KEY] = user.session_version
    session[ADMIN_AUTHENTICATED_KEY] = True
    session[ADMIN_AUTH_TIME_KEY] = 1
    session[ADMIN_PROFILE_ID_KEY] = str(profile.pk)
    session[ADMIN_PROFILE_VERSION_KEY] = profile.version
    session[ADMIN_ROLE_ID_KEY] = str(role.pk) if role else None
    session[ADMIN_ROLE_VERSION_KEY] = role.version if role else None
    session[ADMIN_ROLE_SECURITY_VERSION_KEY] = role.security_version if role else None
    session[ADMIN_POLICY_VERSION_KEY] = policy.security_version if policy else None
    session[ADMIN_AUTH_FACTORS_KEY] = "password"
    session[ADMIN_IP_FINGERPRINT_KEY] = admin_ip_fingerprint(ip_address)
    if step_up:
        request = SimpleNamespace(
            user=user,
            session=session,
            META={"REMOTE_ADDR": ip_address, "HTTP_USER_AGENT": ""},
        )
        grant_admin_step_up(request, security_snapshot(user, request))
    session.save()
    client.force_authenticate(user)
    return client
