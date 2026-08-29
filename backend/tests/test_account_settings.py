from types import SimpleNamespace

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.users.account_settings import (
    AccountCodeRateLimited,
    consume_phone_code_send_limit,
)
from apps.users.authentication import SESSION_VERSION_KEY
from apps.users.models import User
from tests.customer_ownership_helpers import assign_test_customer

CSRF_PATH = "/api/v1/auth/csrf"
LOGIN_PATH = "/api/v1/auth/login/password"
ME_PATH = "/api/v1/me"
PROFILE_PATH = "/api/v1/me/profile"
PHONE_CODE_PATH = "/api/v1/me/phone/code"
PHONE_PATH = "/api/v1/me/phone"
PASSWORD_PATH = "/api/v1/me/password"
APPEARANCE_PATH = "/api/v1/me/appearance"
REVOKE_PATH = "/api/v1/me/sessions/revoke"
PASSWORD = "Correct-Horse-Battery-2026!"
NEW_PASSWORD = "Different-Correct-Horse-2027!"


@pytest.fixture(autouse=True)
def clear_account_rate_limits():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def ordinary_user(db):
    user = User.objects.create_user(
        phone="13800138000",
        nickname="账号用户",
        password=PASSWORD,
    )
    assign_test_customer(user)
    return user


def csrf_client():
    client = APIClient(enforce_csrf_checks=True)
    response = client.get(CSRF_PATH)
    assert response.status_code == 200
    return client, response.json()["data"]["csrf_token"]


def login(client, token, *, phone="13800138000", password=PASSWORD):
    return client.post(
        LOGIN_PATH,
        {"phone": phone, "password": password},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )


def authenticated_client():
    client, token = csrf_client()
    assert login(client, token).status_code == 200
    return client, client.cookies["xianwen_csrf"].value


def write(client, method, path, token, payload):
    return getattr(client, method)(
        path,
        payload,
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )


@pytest.mark.django_db
def test_profile_and_appearance_are_strict_and_persist_across_login(ordinary_user):
    client, token = authenticated_client()

    profile = write(client, "patch", PROFILE_PATH, token, {"nickname": "新的昵称"})
    assert profile.status_code == 200
    assert profile.json()["data"]["nickname"] == "新的昵称"
    assert profile.json()["data"]["appearance"] == {"mode": "system", "accent": "blue"}

    appearance = write(
        client,
        "patch",
        APPEARANCE_PATH,
        token,
        {"mode": "dark", "accent": "purple"},
    )
    assert appearance.status_code == 200
    assert appearance.json()["data"]["appearance"] == {"mode": "dark", "accent": "purple"}

    rejected = write(
        client,
        "patch",
        APPEARANCE_PATH,
        token,
        {"mode": "dark", "accent": "purple", "internal": True},
    )
    assert rejected.status_code == 422

    fresh, fresh_token = csrf_client()
    assert login(fresh, fresh_token).status_code == 200
    assert fresh.get(ME_PATH).json()["data"]["appearance"] == {
        "mode": "dark",
        "accent": "purple",
    }


@pytest.mark.django_db
def test_account_setting_writes_require_csrf_after_login(ordinary_user):
    client, _ = authenticated_client()

    response = client.patch(
        PROFILE_PATH,
        {"nickname": "不能绕过安全校验"},
        format="json",
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_FAILED"
    ordinary_user.refresh_from_db()
    assert ordinary_user.nickname == "账号用户"


@pytest.mark.django_db
def test_phone_code_requires_current_password_and_is_not_a_public_sms_purpose(
    ordinary_user, monkeypatch
):
    client, token = authenticated_client()
    sent = []

    def fake_send(phone, purpose, ip_address):
        sent.append((phone, purpose, ip_address))
        return SimpleNamespace(expires_in=300, resend_after=60)

    monkeypatch.setattr("apps.users.account_views.send_verification_code", fake_send)

    wrong = write(
        client,
        "post",
        PHONE_CODE_PATH,
        token,
        {"phone": "13900139000", "current_password": "Wrong-Password-2026!"},
    )
    assert wrong.status_code == 422
    assert wrong.json()["error"]["code"] == "CURRENT_PASSWORD_INVALID"
    assert sent == []

    success = write(
        client,
        "post",
        PHONE_CODE_PATH,
        token,
        {"phone": "13900139000", "current_password": PASSWORD},
    )
    assert success.status_code == 200
    assert success.json()["data"] == {"sent": True, "expires_in": 300, "resend_after": 60}
    assert sent[0][0:2] == ("+8613900139000", "phone_change")

    public_client, public_token = csrf_client()
    public = write(
        public_client,
        "post",
        "/api/v1/auth/sms/send",
        public_token,
        {"phone": "13900139000", "purpose": "phone_change"},
    )
    assert public.status_code == 422


@pytest.mark.django_db
def test_phone_code_send_has_user_phone_ip_combination_limit(
    ordinary_user, monkeypatch, settings
):
    settings.SMS_LIMIT_COMBINATION_COUNT = 1
    settings.SMS_LIMIT_COMBINATION_WINDOW_SECONDS = 900
    settings.SMS_LIMIT_PHONE_COUNT = 10
    settings.SMS_LIMIT_IP_COUNT = 10
    client, token = authenticated_client()
    sent = []

    def fake_send(phone, purpose, ip_address):
        sent.append((phone, purpose, ip_address))
        return SimpleNamespace(expires_in=300, resend_after=60)

    monkeypatch.setattr("apps.users.account_views.send_verification_code", fake_send)
    payload = {"phone": "13900139000", "current_password": PASSWORD}

    first = write(client, "post", PHONE_CODE_PATH, token, payload)
    second = write(client, "post", PHONE_CODE_PATH, token, payload)

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "RATE_LIMITED"
    assert len(sent) == 1


@pytest.mark.django_db
def test_phone_code_and_confirmation_recheck_phone_uniqueness(ordinary_user, monkeypatch):
    User.objects.create_user(
        phone="13900139000",
        nickname="已有用户",
        password=PASSWORD,
    )
    client, token = authenticated_client()
    monkeypatch.setattr(
        "apps.users.account_views.send_verification_code",
        lambda *args, **kwargs: SimpleNamespace(expires_in=300, resend_after=60),
    )

    code = write(
        client,
        "post",
        PHONE_CODE_PATH,
        token,
        {"phone": "13900139000", "current_password": PASSWORD},
    )
    assert code.status_code == 409
    assert code.json()["error"]["code"] == "PHONE_ALREADY_IN_USE"

    monkeypatch.setattr("apps.users.account_settings.verify_and_consume", lambda *args: True)
    confirmation = write(
        client,
        "patch",
        PHONE_PATH,
        token,
        {"phone": "13900139000", "current_password": PASSWORD, "code": "123456"},
    )
    assert confirmation.status_code == 409
    assert confirmation.json()["error"]["code"] == "PHONE_ALREADY_IN_USE"
    ordinary_user.refresh_from_db()
    assert ordinary_user.phone == "+8613800138000"


@pytest.mark.django_db
def test_phone_change_logs_out_all_sessions_and_requires_new_login(ordinary_user, monkeypatch):
    first, first_token = authenticated_client()
    second, _ = authenticated_client()
    before_version = ordinary_user.session_version
    monkeypatch.setattr("apps.users.account_settings.verify_and_consume", lambda *args: True)

    response = write(
        first,
        "patch",
        PHONE_PATH,
        first_token,
        {"phone": "13900139000", "current_password": PASSWORD, "code": "123456"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"changed": True, "reauthentication_required": True}
    ordinary_user.refresh_from_db()
    assert ordinary_user.phone == "+8613900139000"
    assert ordinary_user.session_version == before_version + 1
    assert first.get(ME_PATH).status_code == 401
    assert second.get(ME_PATH).status_code == 401

    old_phone, old_token = csrf_client()
    assert login(old_phone, old_token).status_code == 401
    new_phone, new_token = csrf_client()
    assert login(new_phone, new_token, phone="13900139000").status_code == 200


@pytest.mark.django_db
def test_password_change_logs_out_all_sessions_and_returns_field_errors(ordinary_user):
    first, first_token = authenticated_client()
    second, _ = authenticated_client()

    weak = write(
        first,
        "patch",
        PASSWORD_PATH,
        first_token,
        {"current_password": PASSWORD, "new_password": "1234567890"},
    )
    assert weak.status_code == 422
    assert "new_password" in weak.json()["error"]["details"]["fields"]
    assert first.get(ME_PATH).status_code == 200

    response = write(
        first,
        "patch",
        PASSWORD_PATH,
        first_token,
        {"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 200
    assert response.json()["data"] == {"changed": True, "reauthentication_required": True}
    assert first.get(ME_PATH).status_code == 401
    assert second.get(ME_PATH).status_code == 401

    old_password, old_token = csrf_client()
    assert login(old_password, old_token).status_code == 401
    new_password, new_token = csrf_client()
    assert login(new_password, new_token, password=NEW_PASSWORD).status_code == 200


@pytest.mark.django_db
def test_revoke_other_sessions_keeps_current_session(ordinary_user):
    current, token = authenticated_client()
    other, _ = authenticated_client()
    old_other_version = other.session[SESSION_VERSION_KEY]

    response = write(
        current,
        "post",
        REVOKE_PATH,
        token,
        {"current_password": PASSWORD},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"revoked": True}
    ordinary_user.refresh_from_db()
    assert ordinary_user.session_version == old_other_version + 1
    assert current.session[SESSION_VERSION_KEY] == ordinary_user.session_version
    assert current.get(ME_PATH).status_code == 200
    assert other.get(ME_PATH).status_code == 401


@pytest.mark.django_db
def test_account_setting_mutations_reject_admin_identities():
    admin = User.objects.create_superuser(
        phone="13900139000",
        nickname="后台管理员",
        password=PASSWORD,
    )
    client = APIClient()
    client.force_authenticate(admin)

    for method, path, payload in (
        ("patch", PROFILE_PATH, {"nickname": "不能修改"}),
        ("patch", APPEARANCE_PATH, {"mode": "dark", "accent": "blue"}),
        ("post", REVOKE_PATH, {"current_password": PASSWORD}),
    ):
        response = getattr(client, method)(path, payload, format="json")
        assert response.status_code == 403


def test_phone_code_send_limit_covers_user_phone_ip_and_combination(settings):
    settings.SMS_LIMIT_PHONE_COUNT = 1
    settings.SMS_LIMIT_PHONE_WINDOW_SECONDS = 3600
    settings.SMS_LIMIT_IP_COUNT = 100
    settings.SMS_LIMIT_IP_WINDOW_SECONDS = 3600
    settings.SMS_LIMIT_COMBINATION_COUNT = 100
    settings.SMS_LIMIT_COMBINATION_WINDOW_SECONDS = 900
    consume_phone_code_send_limit(
        user_id="00000000-0000-4000-8000-000000000001",
        phone="+8613800138000",
        ip_address="192.0.2.1",
    )
    with pytest.raises(AccountCodeRateLimited):
        consume_phone_code_send_limit(
            user_id="00000000-0000-4000-8000-000000000001",
            phone="+8613900139000",
            ip_address="192.0.2.1",
        )

    cache.clear()
    consume_phone_code_send_limit(
        user_id="00000000-0000-4000-8000-000000000001",
        phone="+8613800138000",
        ip_address="192.0.2.1",
    )
    with pytest.raises(AccountCodeRateLimited):
        consume_phone_code_send_limit(
            user_id="00000000-0000-4000-8000-000000000002",
            phone="+8613800138000",
            ip_address="192.0.2.2",
        )

    cache.clear()
    settings.SMS_LIMIT_PHONE_COUNT = 100
    settings.SMS_LIMIT_IP_COUNT = 1
    consume_phone_code_send_limit(
        user_id="00000000-0000-4000-8000-000000000001",
        phone="+8613800138000",
        ip_address="192.0.2.1",
    )
    with pytest.raises(AccountCodeRateLimited):
        consume_phone_code_send_limit(
            user_id="00000000-0000-4000-8000-000000000002",
            phone="+8613900139000",
            ip_address="192.0.2.1",
        )

    cache.clear()
    settings.SMS_LIMIT_IP_COUNT = 100
    settings.SMS_LIMIT_COMBINATION_COUNT = 1
    arguments = {
        "user_id": "00000000-0000-4000-8000-000000000001",
        "phone": "+8613800138000",
        "ip_address": "192.0.2.1",
    }
    consume_phone_code_send_limit(**arguments)
    with pytest.raises(AccountCodeRateLimited):
        consume_phone_code_send_limit(**arguments)
