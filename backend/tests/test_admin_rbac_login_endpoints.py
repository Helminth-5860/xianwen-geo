import uuid

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.admin_rbac.models import AdminRole
from apps.admin_rbac.security import security_snapshot
from apps.admin_rbac.services import change_admin_status, create_admin
from apps.users.models import User

PASSWORD = "Correct-Horse-Battery-2026!"
ME_PATH = "/api/v1/me"


def csrf_client():
    client = APIClient(enforce_csrf_checks=True)
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 200
    return client, response.json()["data"]["csrf_token"]


def password_login(client, token, phone):
    return client.post(
        "/api/v1/admin/auth/login/password",
        {"phone": phone, "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )


def sms_login(client, token, phone):
    password_response = password_login(client, token, phone)
    if password_response.status_code != 200:
        return password_response
    challenge_id = password_response.json()["data"]["challenge_id"]
    sent = client.post(
        "/api/v1/admin/auth/login/sms/send",
        {"challenge_id": challenge_id},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert sent.status_code == 200
    return client.post(
        "/api/v1/admin/auth/login/sms/verify",
        {"challenge_id": challenge_id, "sms_code": "438921"},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )


def assert_unavailable(response):
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ACCOUNT_UNAVAILABLE"
    assert response.json()["request_id"] == response["X-Request-ID"]


@pytest.fixture(autouse=True)
def clear_limits():
    cache.clear()
    yield
    cache.clear()


def admin_fixture():
    actor = User.objects.create_superuser(
        phone="13900139000", nickname="超级管理员", password=PASSWORD
    )
    role = AdminRole.objects.create(name="管理员", data_scope=AdminRole.DataScope.ALL)
    profile = create_admin(
        actor_id=actor.id,
        phone="13700137000",
        nickname="状态管理员",
        password=PASSWORD,
        role_id=role.id,
        request_id=uuid.uuid4(),
    )
    return actor, profile


@pytest.mark.django_db
def test_disabled_locked_enable_unlock_password_login_http_and_old_sessions():
    actor, profile = admin_fixture()
    old_client, old_csrf = csrf_client()
    assert password_login(old_client, old_csrf, profile.user.phone).status_code == 200

    profile = change_admin_status(
        actor_id=actor.id,
        profile_id=profile.id,
        action="disable",
        expected_version=1,
        request_id=uuid.uuid4(),
    )
    assert old_client.get(ME_PATH).status_code == 401
    disabled_client, disabled_csrf = csrf_client()
    assert_unavailable(password_login(disabled_client, disabled_csrf, profile.user.phone))

    profile = change_admin_status(
        actor_id=actor.id,
        profile_id=profile.id,
        action="enable",
        expected_version=2,
        request_id=uuid.uuid4(),
    )
    enabled_client, enabled_csrf = csrf_client()
    assert password_login(enabled_client, enabled_csrf, profile.user.phone).status_code == 200
    assert old_client.get(ME_PATH).status_code == 401

    profile = change_admin_status(
        actor_id=actor.id,
        profile_id=profile.id,
        action="lock",
        expected_version=3,
        request_id=uuid.uuid4(),
    )
    assert enabled_client.get(ME_PATH).status_code == 401
    locked_client, locked_csrf = csrf_client()
    assert_unavailable(password_login(locked_client, locked_csrf, profile.user.phone))

    profile = change_admin_status(
        actor_id=actor.id,
        profile_id=profile.id,
        action="unlock",
        expected_version=4,
        request_id=uuid.uuid4(),
    )
    unlocked_client, unlocked_csrf = csrf_client()
    assert password_login(unlocked_client, unlocked_csrf, profile.user.phone).status_code == 200
    assert enabled_client.get(ME_PATH).status_code == 401


@pytest.mark.django_db
def test_disabled_locked_enable_unlock_sms_login_http_and_old_sessions(monkeypatch):
    actor, profile = admin_fixture()
    profile.role.require_sms_2fa = True
    profile.role.security_version += 1
    profile.role.save(update_fields=["require_sms_2fa", "security_version"])
    monkeypatch.setattr(
        "apps.admin_rbac.security_views.create_admin_challenge",
        lambda snapshot, request: "challenge",
    )
    monkeypatch.setattr(
        "apps.admin_rbac.security_views.send_admin_second_factor",
        lambda challenge_id, request: security_snapshot(profile.user, request),
    )
    monkeypatch.setattr(
        "apps.admin_rbac.security_views.verify_admin_second_factor",
        lambda challenge_id, code, request: security_snapshot(profile.user, request),
    )
    old_client, old_csrf = csrf_client()
    assert sms_login(old_client, old_csrf, profile.user.phone).status_code == 200

    profile = change_admin_status(
        actor_id=actor.id,
        profile_id=profile.id,
        action="disable",
        expected_version=1,
        request_id=uuid.uuid4(),
    )
    assert old_client.get(ME_PATH).status_code == 401
    disabled_client, disabled_csrf = csrf_client()
    assert_unavailable(sms_login(disabled_client, disabled_csrf, profile.user.phone))

    profile = change_admin_status(
        actor_id=actor.id,
        profile_id=profile.id,
        action="enable",
        expected_version=2,
        request_id=uuid.uuid4(),
    )
    enabled_client, enabled_csrf = csrf_client()
    assert sms_login(enabled_client, enabled_csrf, profile.user.phone).status_code == 200
    assert old_client.get(ME_PATH).status_code == 401

    profile = change_admin_status(
        actor_id=actor.id,
        profile_id=profile.id,
        action="lock",
        expected_version=3,
        request_id=uuid.uuid4(),
    )
    assert enabled_client.get(ME_PATH).status_code == 401
    locked_client, locked_csrf = csrf_client()
    assert_unavailable(sms_login(locked_client, locked_csrf, profile.user.phone))

    profile = change_admin_status(
        actor_id=actor.id,
        profile_id=profile.id,
        action="unlock",
        expected_version=4,
        request_id=uuid.uuid4(),
    )
    unlocked_client, unlocked_csrf = csrf_client()
    assert sms_login(unlocked_client, unlocked_csrf, profile.user.phone).status_code == 200
    assert enabled_client.get(ME_PATH).status_code == 401
