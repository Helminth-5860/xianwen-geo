import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from io import StringIO

import pytest
from django.core.management import call_command
from django.db import connection
from django_redis import get_redis_connection
from rest_framework.test import APIClient

from apps.admin_rbac.models import (
    AdminProfile,
    AdminRole,
    AdminSecurityEvent,
    IpAllowlistStatus,
    RoleIpAllowlistEntry,
    SuperuserIpAllowlistEntry,
)
from apps.admin_rbac.security import AdminChallengeStore
from apps.admin_rbac.services import create_admin
from apps.users.authentication import SESSION_VERSION_KEY
from apps.users.models import User
from apps.users.sms.providers import MockSmsProvider, get_sms_provider
from apps.users.sms.purposes import SmsPurpose
from apps.users.sms.security import phone_fingerprint
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


def _sms_send(client, csrf, phone, purpose):
    return client.post(
        "/api/v1/auth/sms/send",
        {"phone": phone, "purpose": purpose},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )


def test_public_login_sms_suppresses_every_admin_identity_without_challenge():
    provider = get_sms_provider()
    assert isinstance(provider, MockSmsProvider)
    role = AdminRole.objects.create(name="短信抑制角色", data_scope=AdminRole.DataScope.ALL)
    actor = make_superuser("13900139001")
    admin_profiles = []
    for index, status in enumerate((AdminProfile.Status.DISABLED, AdminProfile.Status.LOCKED)):
        user = User.objects.create_user(
            phone=f"1370013700{index}", nickname="停用管理员", password=PASSWORD, is_staff=False
        )
        admin_profiles.append(
            AdminProfile.objects.create(user=user, role=role, admin_status=status)
        )
    staff = User.objects.create_user(
        phone="13600136000", nickname="Staff", password=PASSWORD, is_staff=True
    )
    ordinary = User.objects.create_user(phone="13500135000", nickname="普通用户", password=PASSWORD)
    identities = [actor, staff, *(profile.user for profile in admin_profiles)]
    client, csrf = csrf_client()
    baseline = len(provider.outbox)

    for user in identities:
        response = _sms_send(client, csrf, user.phone, "login")
        assert response.status_code == 200
        assert response.json()["data"] == {"sent": True, "expires_in": 300, "resend_after": 60}
        key = f"auth:sms:v1:code:{phone_fingerprint(user.phone)}:{SmsPurpose.LOGIN.value}"
        assert not get_redis_connection("default").exists(key)
    assert len(provider.outbox) == baseline

    normal = _sms_send(client, csrf, ordinary.phone, "login")
    assert normal.status_code == 200
    assert len(provider.outbox) == baseline + 1
    normal_key = f"auth:sms:v1:code:{phone_fingerprint(ordinary.phone)}:{SmsPurpose.LOGIN.value}"
    assert get_redis_connection("default").hget(normal_key, "state") == b"active"


def test_admin_password_reset_cannot_bypass_dedicated_admin_login():
    user = make_superuser("13900139002")
    provider = get_sms_provider()
    assert isinstance(provider, MockSmsProvider)
    client, csrf = csrf_client()
    sent = _sms_send(client, csrf, user.phone, "password_reset")
    assert sent.status_code == 200
    reset_code = provider.outbox[-1].code
    new_password = "New-Correct-Horse-2027!"
    reset = client.post(
        "/api/v1/auth/password/reset",
        {"phone": user.phone, "sms_code": reset_code, "new_password": new_password},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert reset.status_code == 200
    user.refresh_from_db()
    assert user.check_password(new_password)

    ordinary_password = client.post(
        "/api/v1/auth/login/password",
        {"phone": user.phone, "password": new_password},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert ordinary_password.status_code == 403
    assert ordinary_password.json()["error"]["code"] == "ADMIN_LOGIN_REQUIRED"
    ordinary_sms = client.post(
        "/api/v1/auth/login/sms",
        {"phone": user.phone, "sms_code": "000000"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert ordinary_sms.status_code != 200
    assert SESSION_VERSION_KEY not in client.session

    admin_password = client.post(
        "/api/v1/admin/auth/login/password",
        {"phone": user.phone, "password": new_password},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_USER_AGENT="xw-0106-postgres",
    )
    assert admin_password.status_code == 200
    challenge = admin_password.json()["data"]["challenge_id"]
    code = send_code(client, csrf, challenge)
    verified = verify_code(client, csrf, challenge, code)
    assert verified.status_code == 200
    assert SESSION_VERSION_KEY in client.session


def test_disabled_and_locked_admin_password_reset_cannot_restore_public_login():
    role = AdminRole.objects.create(name="重置防绕过角色", data_scope=AdminRole.DataScope.ALL)
    provider = get_sms_provider()
    assert isinstance(provider, MockSmsProvider)

    for index, admin_status in enumerate(
        (AdminProfile.Status.DISABLED, AdminProfile.Status.LOCKED), start=13
    ):
        user = User.objects.create_user(
            phone=f"139001390{index}",
            nickname="受限管理员",
            password=PASSWORD,
            is_staff=False,
        )
        AdminProfile.objects.create(user=user, role=role, admin_status=admin_status)
        client, csrf = csrf_client()
        sent = _sms_send(client, csrf, user.phone, "password_reset")
        assert sent.status_code == 200
        reset_code = provider.outbox[-1].code
        new_password = f"Reset-Admin-{index}-Safe!"
        reset = client.post(
            "/api/v1/auth/password/reset",
            {"phone": user.phone, "sms_code": reset_code, "new_password": new_password},
            format="json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        assert reset.status_code == 200

        ordinary_password = client.post(
            "/api/v1/auth/login/password",
            {"phone": user.phone, "password": new_password},
            format="json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        ordinary_sms = client.post(
            "/api/v1/auth/login/sms",
            {"phone": user.phone, "sms_code": "000000"},
            format="json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        admin_password = client.post(
            "/api/v1/admin/auth/login/password",
            {"phone": user.phone, "password": new_password},
            format="json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_USER_AGENT="xw-0106-postgres",
        )
        assert ordinary_password.status_code == 403
        assert ordinary_password.json()["error"]["code"] == "ADMIN_LOGIN_REQUIRED"
        assert ordinary_sms.status_code == 401
        assert ordinary_sms.json()["error"]["code"] == "AUTH_CREDENTIALS_INVALID"
        assert admin_password.status_code == 403
        assert admin_password.json()["error"]["code"] == "ACCOUNT_UNAVAILABLE"
        assert SESSION_VERSION_KEY not in client.session


def test_admin_challenges_reject_cross_challenge_and_lock_after_five_errors():
    first_user = make_superuser("13900139003")
    second_user = make_superuser("13900139004")
    first_client, first_csrf, first_challenge = password_challenge(first_user)
    first_code = send_code(first_client, first_csrf, first_challenge)
    second_client, second_csrf, second_challenge = password_challenge(second_user)
    second_code = send_code(second_client, second_csrf, second_challenge)

    assert verify_code(first_client, first_csrf, first_challenge, second_code).status_code == 401
    assert verify_code(second_client, second_csrf, second_challenge, first_code).status_code == 401
    assert verify_code(first_client, first_csrf, second_challenge, second_code).status_code == 401

    locked_user = make_superuser("13900139005")
    locked_client, locked_csrf, locked_challenge = password_challenge(locked_user)
    correct_code = send_code(locked_client, locked_csrf, locked_challenge)
    for wrong_code in ("000000", "000001", "000002", "000003", "000004"):
        response = verify_code(locked_client, locked_csrf, locked_challenge, wrong_code)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "ADMIN_AUTH_CHALLENGE_INVALID"
    sixth = verify_code(locked_client, locked_csrf, locked_challenge, correct_code)
    assert sixth.status_code == 401
    assert sixth.json()["error"]["code"] == "ADMIN_AUTH_CHALLENGE_INVALID"


def test_admin_challenge_context_versions_ip_and_device_fail_closed():
    mutations = (
        lambda user: AdminProfile.objects.filter(user=user).update(version=2),
        lambda user: AdminProfile.objects.filter(user=user).update(
            admin_status=AdminProfile.Status.LOCKED
        ),
        lambda user: User.objects.filter(pk=user.pk).update(session_version=2),
        lambda user: (
            type(user.superuser_security_policy)
            .objects.filter(user=user)
            .update(security_version=2)
        ),
    )
    for index, mutate in enumerate(mutations, start=6):
        user = make_superuser(f"1390013900{index}")
        client, csrf, challenge = password_challenge(user)
        mutate(user)
        response = client.post(
            "/api/v1/admin/auth/login/sms/send",
            {"challenge_id": challenge},
            format="json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_USER_AGENT="xw-0106-postgres",
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "ADMIN_AUTH_CHALLENGE_INVALID"

    user = make_superuser("13900139010")
    client, csrf, challenge = password_challenge(user)
    changed_ip = client.post(
        "/api/v1/admin/auth/login/sms/send",
        {"challenge_id": challenge},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_USER_AGENT="xw-0106-postgres",
        REMOTE_ADDR="192.0.2.9",
    )
    changed_device = client.post(
        "/api/v1/admin/auth/login/sms/send",
        {"challenge_id": challenge},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_USER_AGENT="different-device",
    )
    assert changed_ip.status_code == 401
    assert changed_device.status_code == 401


def test_superuser_allowlist_full_api_and_every_request_enforcement(settings):
    user = make_superuser("13900139011")
    policy = user.superuser_security_policy
    assert policy.ip_allowlist_enabled is False
    admin = authenticate_admin_client(APIClient(), user)
    base = "/api/v1/admin/security/superuser"
    assert admin.get(base).status_code == 200

    wrong = admin.post(
        f"{base}/ip-allowlist",
        {
            "network_cidr": "127.0.0.1",
            "current_password": "wrong-password",
            "expected_security_version": 1,
        },
        format="json",
    )
    assert wrong.status_code == 403
    ipv4 = admin.post(
        f"{base}/ip-allowlist",
        {
            "network_cidr": "127.0.0.1",
            "current_password": PASSWORD,
            "expected_security_version": 1,
        },
        format="json",
    )
    assert ipv4.status_code == 201
    assert ipv4.json()["data"]["entry"]["network_cidr"] == "127.0.0.1/32"
    policy.refresh_from_db()
    admin = authenticate_admin_client(APIClient(), user)
    ipv6 = admin.post(
        f"{base}/ip-allowlist",
        {
            "network_cidr": "2001:db8::8",
            "current_password": PASSWORD,
            "expected_security_version": policy.security_version,
        },
        format="json",
    )
    assert ipv6.status_code == 201
    assert ipv6.json()["data"]["entry"]["network_cidr"] == "2001:db8::8/128"

    policy.refresh_from_db()
    for invalid in ("example.com", "10.*", "10.0.0.1\n", "not-an-ip"):
        admin = authenticate_admin_client(APIClient(), user)
        response = admin.post(
            f"{base}/ip-allowlist",
            {
                "network_cidr": invalid,
                "current_password": PASSWORD,
                "expected_security_version": policy.security_version,
            },
            format="json",
        )
        assert response.status_code == 422

    SuperuserIpAllowlistEntry.objects.filter(policy=policy).update(
        status=IpAllowlistStatus.INACTIVE
    )
    admin = authenticate_admin_client(APIClient(), user)
    no_active = admin.patch(
        base,
        {
            "ip_allowlist_enabled": True,
            "current_password": PASSWORD,
            "expected_security_version": policy.security_version,
        },
        format="json",
    )
    assert no_active.status_code == 409
    SuperuserIpAllowlistEntry.objects.filter(policy=policy, network_cidr="127.0.0.1/32").update(
        status=IpAllowlistStatus.ACTIVE
    )
    policy.refresh_from_db()
    admin = authenticate_admin_client(APIClient(), user)
    enabled = admin.patch(
        base,
        {
            "ip_allowlist_enabled": True,
            "current_password": PASSWORD,
            "expected_security_version": policy.security_version,
        },
        format="json",
    )
    assert enabled.status_code == 200
    assert admin.get("/api/v1/admin/me").status_code == 403

    allowed = authenticate_admin_client(APIClient(), user, ip_address="127.0.0.1")
    denied = authenticate_admin_client(APIClient(), user, ip_address="192.0.2.8")
    assert allowed.get("/api/v1/admin/me", REMOTE_ADDR="127.0.0.1").status_code == 200
    assert denied.get("/api/v1/admin/me", REMOTE_ADDR="192.0.2.8").status_code == 403

    conflict = allowed.patch(
        base,
        {
            "ip_allowlist_enabled": True,
            "current_password": PASSWORD,
            "expected_security_version": 1,
        },
        format="json",
        REMOTE_ADDR="127.0.0.1",
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "SECURITY_POLICY_VERSION_CONFLICT"

    lockout_user = make_superuser("13900139016")
    lockout_policy = lockout_user.superuser_security_policy
    lockout_admin = authenticate_admin_client(APIClient(), lockout_user)
    lockout_entry = lockout_admin.post(
        f"{base}/ip-allowlist",
        {
            "network_cidr": "192.0.2.0/24",
            "current_password": PASSWORD,
            "expected_security_version": lockout_policy.security_version,
        },
        format="json",
    )
    assert lockout_entry.status_code == 201
    lockout_policy.refresh_from_db()
    challenge_client, challenge_csrf, unfinished = password_challenge(lockout_user)
    lockout_admin = authenticate_admin_client(APIClient(), lockout_user)
    first_lockout = lockout_admin.patch(
        base,
        {
            "ip_allowlist_enabled": True,
            "current_password": PASSWORD,
            "expected_security_version": lockout_policy.security_version,
        },
        format="json",
    )
    assert first_lockout.status_code == 409
    assert first_lockout.json()["error"]["code"] == "IP_ALLOWLIST_LOCKOUT_CONFIRMATION_REQUIRED"
    confirmed = lockout_admin.patch(
        base,
        {
            "ip_allowlist_enabled": True,
            "current_password": PASSWORD,
            "expected_security_version": lockout_policy.security_version,
            "confirm_lockout": True,
        },
        format="json",
    )
    assert confirmed.status_code == 200
    assert lockout_admin.get("/api/v1/admin/me").status_code == 403
    invalidated = challenge_client.post(
        "/api/v1/admin/auth/login/sms/send",
        {"challenge_id": unfinished},
        format="json",
        HTTP_X_CSRFTOKEN=challenge_csrf,
        HTTP_USER_AGENT="xw-0106-postgres",
    )
    assert invalidated.status_code == 401
    assert invalidated.json()["error"]["code"] == "ADMIN_AUTH_CHALLENGE_INVALID"

    settings.ADMIN_REAUTH_LIMIT_FAILURES = 1
    limited_user = make_superuser("13900139017")
    limited_policy = limited_user.superuser_security_policy
    limited_admin = authenticate_admin_client(APIClient(), limited_user)
    failed_reauth = limited_admin.patch(
        base,
        {
            "ip_allowlist_enabled": False,
            "current_password": "wrong-password",
            "expected_security_version": limited_policy.security_version,
        },
        format="json",
    )
    rate_limited = limited_admin.patch(
        base,
        {
            "ip_allowlist_enabled": False,
            "current_password": PASSWORD,
            "expected_security_version": limited_policy.security_version,
        },
        format="json",
    )
    assert failed_reauth.status_code == 403
    assert failed_reauth.json()["error"]["code"] == "ADMIN_REAUTH_FAILED"
    assert rate_limited.status_code == 429
    assert rate_limited.json()["error"]["code"] == "RATE_LIMITED"
    ordinary_actor, profile, _ = make_admin(require_sms_2fa=False)
    ordinary = authenticate_admin_client(APIClient(), profile.user)
    assert ordinary.get(base).status_code == 403
    assert ordinary.patch(base, {}, format="json").status_code == 403


def test_superuser_emergency_recovery_and_self_force_logout_are_session_only():
    user = make_superuser("13900139012")
    policy = user.superuser_security_policy
    policy.ip_allowlist_enabled = True
    policy.save(update_fields=["ip_allowlist_enabled"])
    SuperuserIpAllowlistEntry.objects.create(
        policy=policy, network_cidr="127.0.0.1/32", ip_version=4, label="console"
    )
    client, csrf, challenge = password_challenge(user)
    code = send_code(client, csrf, challenge)
    assert verify_code(client, csrf, challenge, code).status_code == 200
    initial_policy_version = policy.security_version
    initial_session_version = user.session_version
    dry_output = StringIO()
    call_command(
        "recover_admin_ip_allowlist", "--superuser-id", str(user.id), "--dry-run", stdout=dry_output
    )
    policy.refresh_from_db()
    user.refresh_from_db()
    assert policy.ip_allowlist_enabled is True
    assert policy.security_version == initial_policy_version
    assert user.session_version == initial_session_version

    output = StringIO()
    call_command("recover_admin_ip_allowlist", "--superuser-id", str(user.id), stdout=output)
    policy.refresh_from_db()
    user.refresh_from_db()
    assert policy.ip_allowlist_enabled is False
    assert policy.security_version == initial_policy_version + 1
    assert user.session_version == initial_session_version + 1
    assert client.get("/api/v1/me").status_code == 401
    event = AdminSecurityEvent.objects.get(event_type="emergency_recovery_used", subject=user)
    assert event.policy_version == policy.security_version
    text = dry_output.getvalue() + output.getvalue()
    for forbidden in (user.phone, "127.0.0.1", PASSWORD, "session", "bypass"):
        assert forbidden not in text.lower()
    call_command("recover_admin_ip_allowlist", "--superuser-id", str(user.id))
    policy.refresh_from_db()
    user.refresh_from_db()
    assert policy.security_version == initial_policy_version + 1
    assert user.session_version == initial_session_version + 1

    get_redis_connection("default").flushdb()
    fresh_client, fresh_csrf, fresh_challenge = password_challenge(user)
    fresh_code = send_code(fresh_client, fresh_csrf, fresh_challenge)
    assert verify_code(fresh_client, fresh_csrf, fresh_challenge, fresh_code).status_code == 200
    fresh_csrf = fresh_client.get("/api/v1/auth/csrf").json()["data"]["csrf_token"]
    before_force = user.session_version
    profile = user.admin_profile
    forced = fresh_client.post(
        f"/api/v1/admin/admins/{profile.id}/force-logout",
        {},
        format="json",
        HTTP_X_CSRFTOKEN=fresh_csrf,
        HTTP_USER_AGENT="xw-0106-postgres",
    )
    assert forced.status_code == 200
    user.refresh_from_db()
    profile.refresh_from_db()
    assert user.session_version == before_force + 1
    assert user.is_superuser is True and user.is_staff is True
    assert profile.admin_status == AdminProfile.Status.ACTIVE
    assert fresh_client.get("/api/v1/me").status_code == 401
    assert AdminSecurityEvent.objects.filter(
        event_type="admin_forced_logout", actor=user, subject=user
    ).exists()
