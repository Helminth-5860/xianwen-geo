import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.core.management import call_command
from django.db import connection
from django_redis import get_redis_connection
from rest_framework.test import APIClient

from apps.admin_rbac.models import AdminRole, RoleIpAllowlistEntry
from apps.admin_rbac.security import AdminChallengeStore
from apps.admin_rbac.services import create_admin
from apps.users.models import User
from apps.users.sms.providers import MockSmsProvider, get_sms_provider
from tests.admin_session_helpers import authenticate_admin_client

pytestmark = pytest.mark.django_db(transaction=True)
PASSWORD = "Correct-Horse-Battery-2026!"


def require_postgresql():
    if connection.vendor != "postgresql":
        pytest.skip("仅通过 scripts/test-admin-security.* 在真实 PostgreSQL/Redis 执行。")


@pytest.fixture(autouse=True)
def real_infrastructure():
    require_postgresql()
    redis = get_redis_connection("default")
    redis.ping()
    redis.flushdb()
    yield
    redis.flushdb()


def csrf_client():
    client = APIClient(enforce_csrf_checks=True)
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 200
    return client, response.json()["data"]["csrf_token"]


def make_superuser(phone="13900139000"):
    return User.objects.create_superuser(phone=phone, nickname="超级管理员", password=PASSWORD)


def make_admin(*, require_sms_2fa=True):
    actor = make_superuser()
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


def password_challenge(user):
    client, csrf = csrf_client()
    response = client.post(
        "/api/v1/admin/auth/login/password",
        {"phone": user.phone, "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_USER_AGENT="xw-0106-postgres",
    )
    assert response.status_code == 200
    assert response.json()["data"]["requires_2fa"] is True
    return client, csrf, response.json()["data"]["challenge_id"]


def send_code(client, csrf, challenge):
    provider = get_sms_provider()
    assert isinstance(provider, MockSmsProvider)
    response = client.post(
        "/api/v1/admin/auth/login/sms/send",
        {"challenge_id": challenge},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_USER_AGENT="xw-0106-postgres",
    )
    assert response.status_code == 200
    return provider.outbox[-1].code


def verify_code(client, csrf, challenge, code):
    return client.post(
        "/api/v1/admin/auth/login/sms/verify",
        {"challenge_id": challenge, "sms_code": code},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_USER_AGENT="xw-0106-postgres",
    )


def test_postgresql_redis_superuser_two_factor_is_one_time_and_keys_are_fingerprinted():
    user = make_superuser()
    client, csrf, challenge = password_challenge(user)
    code = send_code(client, csrf, challenge)
    challenge_ttl = get_redis_connection("default").ttl(AdminChallengeStore.key(challenge))
    assert 240 <= challenge_ttl <= 300

    first = verify_code(client, csrf, challenge, code)
    refreshed_csrf = client.get("/api/v1/auth/csrf").json()["data"]["csrf_token"]
    replay = verify_code(client, refreshed_csrf, challenge, code)

    assert first.status_code == 200
    assert client.get("/api/v1/admin/me", HTTP_USER_AGENT="xw-0106-postgres").status_code == 200
    assert replay.status_code == 401
    keys = [
        item.decode() for item in get_redis_connection("default").scan_iter("auth:admin-login:*")
    ]
    joined = " ".join(keys)
    assert challenge not in joined
    assert user.phone not in joined
    assert "127.0.0.1" not in joined


def test_postgresql_redis_concurrent_verify_consumes_exactly_once():
    user = make_superuser()
    client, csrf, challenge = password_challenge(user)
    send_code(client, csrf, challenge)
    store = AdminChallengeStore()
    key = store.key(challenge)
    digest = get_redis_connection("default").hget(key, "code_digest").decode()
    barrier = threading.Barrier(2)

    def consume():
        barrier.wait()
        return AdminChallengeStore().verify(challenge, digest)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result() for future in (pool.submit(consume), pool.submit(consume))]
    assert sorted(results) == ["consumed", "replayed"]


def test_postgresql_role_change_invalidates_unfinished_challenge():
    _, profile, role = make_admin()
    client, csrf, challenge = password_challenge(profile.user)
    device_mismatch = client.post(
        "/api/v1/admin/auth/login/sms/send",
        {"challenge_id": challenge},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_USER_AGENT="different-device",
    )
    assert device_mismatch.status_code == 401
    role.security_version += 1
    role.save(update_fields=["security_version"])

    response = client.post(
        "/api/v1/admin/auth/login/sms/send",
        {"challenge_id": challenge},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_USER_AGENT="xw-0106-postgres",
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "ADMIN_AUTH_CHALLENGE_INVALID"


def test_postgresql_role_ip_allowlist_enforces_each_request_and_ipv6():
    _, profile, role = make_admin(require_sms_2fa=False)
    role.ip_allowlist_enabled = True
    role.save(update_fields=["ip_allowlist_enabled"])
    RoleIpAllowlistEntry.objects.create(
        role=role, network_cidr="2001:db8::/64", ip_version=6, label="IPv6 office"
    )
    allowed = authenticate_admin_client(APIClient(), profile.user, ip_address="2001:db8::8")
    denied = authenticate_admin_client(APIClient(), profile.user, ip_address="198.51.100.8")

    assert (
        allowed.post(
            "/api/v1/admin/auth/logout", {}, format="json", REMOTE_ADDR="2001:db8::8"
        ).status_code
        == 200
    )
    assert (
        denied.post(
            "/api/v1/admin/auth/logout",
            {},
            format="json",
            REMOTE_ADDR="198.51.100.8",
            HTTP_X_FORWARDED_FOR="2001:db8::8",
        ).status_code
        == 403
    )


def test_postgresql_security_write_requires_password_version_and_revokes_sessions():
    actor, profile, role = make_admin(require_sms_2fa=False)
    old = authenticate_admin_client(APIClient(), profile.user)
    admin = authenticate_admin_client(APIClient(), actor)
    before = profile.user.session_version
    wrong = admin.patch(
        f"/api/v1/admin/roles/{role.id}/security",
        {
            "current_password": "not-the-password",
            "expected_security_version": 1,
            "require_sms_2fa": True,
        },
        format="json",
    )
    changed = admin.patch(
        f"/api/v1/admin/roles/{role.id}/security",
        {
            "current_password": PASSWORD,
            "expected_security_version": 1,
            "require_sms_2fa": True,
        },
        format="json",
    )

    assert wrong.status_code == 403
    assert changed.status_code == 200
    profile.user.refresh_from_db()
    assert profile.user.session_version == before + 1
    assert old.post("/api/v1/admin/auth/logout", {}, format="json").status_code == 403


def test_postgresql_lockout_confirmation_and_version_conflict_are_stable():
    actor, _, role = make_admin(require_sms_2fa=False)
    RoleIpAllowlistEntry.objects.create(
        role=role, network_cidr="192.0.2.0/24", ip_version=4, label="other network"
    )
    admin = authenticate_admin_client(APIClient(), actor, ip_address="198.51.100.8")
    first = admin.patch(
        f"/api/v1/admin/roles/{role.id}/security",
        {
            "current_password": PASSWORD,
            "expected_security_version": 1,
            "ip_allowlist_enabled": True,
        },
        format="json",
        REMOTE_ADDR="198.51.100.8",
    )
    confirmed = admin.patch(
        f"/api/v1/admin/roles/{role.id}/security",
        {
            "current_password": PASSWORD,
            "expected_security_version": 1,
            "ip_allowlist_enabled": True,
            "confirm_lockout": True,
        },
        format="json",
        REMOTE_ADDR="198.51.100.8",
    )
    conflict = admin.patch(
        f"/api/v1/admin/roles/{role.id}/security",
        {
            "current_password": PASSWORD,
            "expected_security_version": 1,
            "require_sms_2fa": True,
        },
        format="json",
        REMOTE_ADDR="198.51.100.8",
    )
    assert first.status_code == 409
    assert first.json()["error"]["code"] == "IP_ALLOWLIST_LOCKOUT_CONFIRMATION_REQUIRED"
    assert confirmed.status_code == 200
    assert conflict.status_code in {403, 409}


def test_postgresql_emergency_recovery_dry_run_apply_and_idempotency():
    _, _, role = make_admin(require_sms_2fa=False)
    role.ip_allowlist_enabled = True
    role.save(update_fields=["ip_allowlist_enabled"])
    initial = role.security_version

    call_command("recover_admin_ip_allowlist", "--role-id", str(role.id), "--dry-run")
    role.refresh_from_db()
    assert role.ip_allowlist_enabled is True
    assert role.security_version == initial

    call_command("recover_admin_ip_allowlist", "--role-id", str(role.id))
    role.refresh_from_db()
    assert role.ip_allowlist_enabled is False
    assert role.security_version == initial + 1
    call_command("recover_admin_ip_allowlist", "--role-id", str(role.id))
    role.refresh_from_db()
    assert role.security_version == initial + 1
