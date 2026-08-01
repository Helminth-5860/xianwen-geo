import uuid
from pathlib import Path

import pytest
from django.contrib.auth import SESSION_KEY
from rest_framework.test import APIClient

from apps.admin_rbac.models import (
    AdminProfile,
    AdminRole,
    AdminSecurityEvent,
    RoleIpAllowlistEntry,
)
from apps.admin_rbac.security import (
    ADMIN_AUTHENTICATED_KEY,
    AdminIpNotAllowed,
    normalize_network,
    security_snapshot,
)
from apps.admin_rbac.services import create_admin
from apps.users.models import User
from tests.admin_session_helpers import authenticate_admin_client

PASSWORD = "Correct-Horse-Battery-2026!"


def csrf_client():
    client = APIClient(enforce_csrf_checks=True)
    response = client.get("/api/v1/auth/csrf")
    return client, response.json()["data"]["csrf_token"]


def superuser():
    return User.objects.create_superuser(
        phone="13900139000", nickname="超级管理员", password=PASSWORD
    )


def ordinary_admin(*, require_sms_2fa=False):
    actor = superuser()
    role = AdminRole.objects.create(
        name="安全管理员", data_scope=AdminRole.DataScope.ALL, require_sms_2fa=require_sms_2fa
    )
    profile = create_admin(
        actor_id=actor.id,
        phone="13700137000",
        nickname="普通管理员",
        password=PASSWORD,
        role_id=role.id,
        request_id=uuid.uuid4(),
    )
    return actor, profile, role


@pytest.mark.django_db
def test_superuser_password_step_always_requires_sms_without_django_login(monkeypatch):
    user = superuser()
    monkeypatch.setattr(
        "apps.admin_rbac.security_views.create_admin_challenge",
        lambda snapshot, request: "opaque-challenge",
    )
    client, csrf = csrf_client()

    response = client.post(
        "/api/v1/admin/auth/login/password",
        {"phone": user.phone, "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "requires_2fa": True,
        "challenge_id": "opaque-challenge",
        "expires_in": 300,
    }
    assert SESSION_KEY not in client.session
    assert ADMIN_AUTHENTICATED_KEY not in client.session


@pytest.mark.django_db
def test_ordinary_role_2fa_switch_controls_password_completion(monkeypatch):
    _, profile, role = ordinary_admin(require_sms_2fa=False)
    client, csrf = csrf_client()
    complete = client.post(
        "/api/v1/admin/auth/login/password",
        {"phone": profile.user.phone, "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert complete.status_code == 200
    assert complete.json()["data"]["requires_2fa"] is False
    assert client.session[ADMIN_AUTHENTICATED_KEY] is True

    role.require_sms_2fa = True
    role.security_version += 1
    role.save(update_fields=["require_sms_2fa", "security_version"])
    monkeypatch.setattr(
        "apps.admin_rbac.security_views.create_admin_challenge",
        lambda snapshot, request: "next-challenge",
    )
    second, csrf2 = csrf_client()
    challenged = second.post(
        "/api/v1/admin/auth/login/password",
        {"phone": profile.user.phone, "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf2,
    )
    assert challenged.status_code == 200
    assert challenged.json()["data"]["requires_2fa"] is True
    assert SESSION_KEY not in second.session


@pytest.mark.django_db
def test_admin_profile_identity_cannot_use_ordinary_password_or_sms_login(monkeypatch):
    _, profile, _ = ordinary_admin()
    profile.admin_status = AdminProfile.Status.DISABLED
    profile.save(update_fields=["admin_status"])
    User.objects.filter(pk=profile.user_id).update(is_staff=False)
    profile.user.refresh_from_db()
    client, csrf = csrf_client()

    password = client.post(
        "/api/v1/auth/login/password",
        {"phone": profile.user.phone, "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    monkeypatch.setattr("apps.users.views.verify_and_consume", lambda *args, **kwargs: True)
    sms = client.post(
        "/api/v1/auth/login/sms",
        {"phone": profile.user.phone, "sms_code": "618294"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )

    assert password.status_code == 403
    assert password.json()["error"]["code"] == "ADMIN_LOGIN_REQUIRED"
    assert sms.status_code == 403
    assert sms.json()["error"]["code"] == "ADMIN_LOGIN_REQUIRED"
    assert SESSION_KEY not in client.session


@pytest.mark.django_db
def test_public_sms_endpoint_rejects_internal_admin_purpose():
    client, csrf = csrf_client()
    response = client.post(
        "/api/v1/auth/sms/send",
        {"phone": "13800138000", "purpose": "admin_login_2fa"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.django_db
def test_legacy_staff_session_and_promoted_user_session_lack_admin_context():
    user = User.objects.create_user(phone="13800138000", nickname="后提升用户", password=PASSWORD)
    client = APIClient()
    client.force_authenticate(user)
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    AdminProfile.objects.create(user=user, admin_status=AdminProfile.Status.ACTIVE)

    response = client.get("/api/v1/admin/me")

    assert response.status_code == 403
    assert ADMIN_AUTHENTICATED_KEY not in client.session


@pytest.mark.django_db
def test_role_security_version_change_revokes_existing_admin_context():
    _, profile, role = ordinary_admin()
    client = authenticate_admin_client(APIClient(), profile.user)
    role.security_version += 1
    role.save(update_fields=["security_version"])

    response = client.post("/api/v1/admin/auth/logout", {}, format="json")

    assert response.status_code == 403
    assert ADMIN_AUTHENTICATED_KEY not in client.session


@pytest.mark.django_db
def test_ip_normalization_and_allowlist_support_ipv4_ipv6_and_reject_unsafe_values():
    assert normalize_network("192.0.2.8") == ("192.0.2.8/32", 4)
    assert normalize_network("2001:db8::7") == ("2001:db8::7/128", 6)
    assert normalize_network("2001:db8::1/64") == ("2001:db8::/64", 6)
    for value in ("example.com", "10.*", "10.0.0.1\\d+", "10.0.0.1\n"):
        with pytest.raises(ValueError):
            normalize_network(value)


@pytest.mark.django_db
def test_every_request_enforces_ip_allowlist_and_ignores_untrusted_xff():
    _, profile, role = ordinary_admin()
    role.ip_allowlist_enabled = True
    role.save(update_fields=["ip_allowlist_enabled"])
    RoleIpAllowlistEntry.objects.create(
        role=role, network_cidr="192.0.2.0/24", ip_version=4, label="office"
    )
    request = type(
        "Request",
        (),
        {
            "META": {
                "REMOTE_ADDR": "198.51.100.9",
                "HTTP_X_FORWARDED_FOR": "192.0.2.8",
                "HTTP_USER_AGENT": "pytest",
            }
        },
    )()
    with pytest.raises(AdminIpNotAllowed):
        security_snapshot(profile.user, request)


@pytest.mark.django_db
def test_force_logout_increments_version_and_records_redacted_event():
    actor, profile, _ = ordinary_admin()
    first, first_csrf = csrf_client()
    second, second_csrf = csrf_client()
    for client, token in ((first, first_csrf), (second, second_csrf)):
        login_response = client.post(
            "/api/v1/admin/auth/login/password",
            {"phone": profile.user.phone, "password": PASSWORD},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )
        assert login_response.status_code == 200
    admin = authenticate_admin_client(APIClient(), actor)
    before = profile.user.session_version

    response = admin.post(f"/api/v1/admin/admins/{profile.id}/force-logout", {}, format="json")

    assert response.status_code == 200
    profile.user.refresh_from_db()
    assert profile.user.session_version == before + 1
    assert first.get("/api/v1/me").status_code == 401
    assert second.get("/api/v1/me").status_code == 401
    event = AdminSecurityEvent.objects.get(event_type="admin_forced_logout")
    serialized = str(event.__dict__)
    for forbidden in (PASSWORD, profile.user.phone, "challenge", "sms_code"):
        assert forbidden not in serialized


@pytest.mark.django_db
def test_superuser_policy_is_created_and_normal_admin_cannot_read_security_pages():
    actor, profile, role = ordinary_admin()
    assert actor.superuser_security_policy.ip_allowlist_enabled is False
    client = authenticate_admin_client(APIClient(), profile.user)
    assert client.get(f"/api/v1/admin/roles/{role.id}/security").status_code == 403
    assert client.get("/api/v1/admin/security/superuser").status_code == 403


@pytest.mark.django_db
def test_invalid_cidr_is_stable_422_and_redis_failure_closes_admin_login(monkeypatch):
    actor = superuser()
    admin = authenticate_admin_client(APIClient(), actor)
    role = AdminRole.objects.create(name="CIDR", data_scope=AdminRole.DataScope.ALL)
    invalid = admin.post(
        f"/api/v1/admin/roles/{role.id}/ip-allowlist",
        {
            "network_cidr": "example.com",
            "label": "unsafe",
            "current_password": PASSWORD,
            "expected_security_version": 1,
        },
        format="json",
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"

    from apps.admin_rbac.security import AdminSecurityUnavailable

    monkeypatch.setattr(
        "apps.admin_rbac.security_views.create_admin_challenge",
        lambda snapshot, request: (_ for _ in ()).throw(AdminSecurityUnavailable()),
    )
    client, csrf = csrf_client()
    unavailable = client.post(
        "/api/v1/admin/auth/login/password",
        {"phone": actor.phone, "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "SERVICE_TEMPORARILY_UNAVAILABLE"


def test_migration_reverse_limit_and_emergency_recovery_documentation_are_preserved():
    root = Path(__file__).resolve().parents[2]
    migration = (
        root / "backend/apps/admin_rbac/migrations/0005_initialize_superuser_security_policies.py"
    ).read_text(encoding="utf-8")
    documentation = (root / "docs/20-ADMIN-2FA-IP-ALLOWLIST.md").read_text(encoding="utf-8")
    assert "migrations.RunPython.noop" in migration
    assert "完整回退" in documentation and "0004" in documentation
    assert "recover_admin_ip_allowlist" in documentation
    assert "腾讯云 PostgreSQL/Redis" in documentation


@pytest.mark.django_db
def test_current_password_reauth_is_short_lived_rate_limited(settings):
    settings.ADMIN_REAUTH_LIMIT_FAILURES = 1
    settings.ADMIN_REAUTH_LIMIT_WINDOW_SECONDS = 60
    actor = superuser()
    role = AdminRole.objects.create(name="限流角色", data_scope=AdminRole.DataScope.ALL)
    client = authenticate_admin_client(APIClient(), actor)
    path = f"/api/v1/admin/roles/{role.id}/security"
    wrong = client.patch(
        path,
        {
            "current_password": "wrong-password",
            "expected_security_version": 1,
            "require_sms_2fa": True,
        },
        format="json",
    )
    limited = client.patch(
        path,
        {
            "current_password": PASSWORD,
            "expected_security_version": 1,
            "require_sms_2fa": True,
        },
        format="json",
    )
    assert wrong.status_code == 403
    assert wrong.json()["error"]["code"] == "ADMIN_REAUTH_FAILED"
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"
    role.refresh_from_db()
    assert role.require_sms_2fa is False


@pytest.mark.django_db
def test_admin_security_missing_role_and_allowlist_entries_are_stable_404():
    actor = User.objects.create_superuser(
        phone="13900139099", nickname="404 超级管理员", password=PASSWORD
    )
    client = authenticate_admin_client(
        APIClient(REMOTE_ADDR="198.51.100.99"), actor, ip_address="198.51.100.99"
    )
    missing = uuid.uuid4()
    mutation = {
        "current_password": PASSWORD,
        "expected_security_version": 1,
        "require_sms_2fa": True,
    }
    create_entry = {
        "network_cidr": "203.0.113.8",
        "current_password": PASSWORD,
        "expected_security_version": 1,
    }
    assert client.get(f"/api/v1/admin/roles/{missing}/security").status_code == 404
    assert (
        client.patch(f"/api/v1/admin/roles/{missing}/security", mutation, format="json").status_code
        == 404
    )
    assert client.get(f"/api/v1/admin/roles/{missing}/ip-allowlist").status_code == 404
    assert (
        client.post(
            f"/api/v1/admin/roles/{missing}/ip-allowlist", create_entry, format="json"
        ).status_code
        == 404
    )

    role = AdminRole.objects.create(name="404 边界角色", data_scope=AdminRole.DataScope.ALL)
    update_entry = {
        "status": "inactive",
        "current_password": PASSWORD,
        "expected_security_version": role.security_version,
    }
    assert (
        client.patch(
            f"/api/v1/admin/roles/{role.id}/ip-allowlist/{missing}",
            update_entry,
            format="json",
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/v1/admin/security/superuser/ip-allowlist/{missing}",
            update_entry,
            format="json",
        ).status_code
        == 404
    )


def test_admin_redis_script_recovers_from_noscript():
    from redis.exceptions import NoScriptError

    from apps.admin_rbac.security import RedisScript

    class FakeRedis:
        def __init__(self):
            self.loads = 0
            self.calls = 0

        def script_load(self, source):
            self.loads += 1
            return f"sha-{self.loads}"

        def evalsha(self, sha, key_count, *args):
            self.calls += 1
            if self.calls == 1:
                raise NoScriptError
            return b"recovered"

    client = FakeRedis()
    script = RedisScript("return 'ok'")
    assert script.run(client, ["fingerprinted-key"], ["value"]) == b"recovered"
    assert client.loads == 2
    assert client.calls == 2
