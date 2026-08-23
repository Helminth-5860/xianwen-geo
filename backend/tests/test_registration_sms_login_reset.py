import logging

import pytest
from django.core.cache import cache
from django.db import DatabaseError
from rest_framework.test import APIClient

from apps.admin_rbac.registration_links import issue_registration_ref
from apps.users.authentication import SESSION_VERSION_KEY
from apps.users.models import LoginEvent, Tenant, User
from apps.users.sms.exceptions import SmsServiceUnavailable
from tests.customer_ownership_helpers import assign_test_customer, create_test_admin

CSRF_PATH = "/api/v1/auth/csrf"
REGISTER_PATH = "/api/v1/auth/register"
PASSWORD_LOGIN_PATH = "/api/v1/auth/login/password"
SMS_LOGIN_PATH = "/api/v1/auth/login/sms"
PASSWORD_RESET_PATH = "/api/v1/auth/password/reset"
ME_PATH = "/api/v1/me"
STRONG_PASSWORD = "Correct-Horse-Battery-2026!"
NEW_PASSWORD = "New-Correct-Horse-2027!"


@pytest.fixture(autouse=True)
def clear_rate_limits():
    cache.clear()
    yield
    cache.clear()


def csrf_client():
    client = APIClient(enforce_csrf_checks=True)
    response = client.get(CSRF_PATH)
    assert response.status_code == 200
    return client, response.json()["data"]["csrf_token"]


def post_with_csrf(client, path, token, data):
    return client.post(path, data=data, format="json", HTTP_X_CSRFTOKEN=token)


def create_user(phone="13800138000", **kwargs):
    return User.objects.create_user(
        phone=phone,
        nickname=kwargs.pop("nickname", "认证用户"),
        password=kwargs.pop("password", STRONG_PASSWORD),
        **kwargs,
    )


def password_login(client, token, phone="13800138000", password=STRONG_PASSWORD):
    return post_with_csrf(
        client,
        PASSWORD_LOGIN_PATH,
        token,
        {"phone": phone, "password": password},
    )


def valid_registration_ref():
    owner = create_test_admin(tenant=Tenant.legacy_default())
    return issue_registration_ref(owner)


@pytest.mark.django_db
@pytest.mark.parametrize("path", [REGISTER_PATH, SMS_LOGIN_PATH, PASSWORD_RESET_PATH])
def test_new_anonymous_endpoints_require_real_csrf(path):
    payloads = {
        REGISTER_PATH: {
            "phone": "13800138000",
            "nickname": "测试用户",
            "sms_code": "438921",
            "password": STRONG_PASSWORD,
        },
        SMS_LOGIN_PATH: {"phone": "13800138000", "sms_code": "438921"},
        PASSWORD_RESET_PATH: {
            "phone": "13800138000",
            "sms_code": "438921",
            "new_password": NEW_PASSWORD,
        },
    }
    response = APIClient(enforce_csrf_checks=True).post(path, payloads[path], format="json")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_FAILED"


@pytest.mark.django_db
def test_registration_consumes_code_creates_approved_active_user_and_logs_in(monkeypatch):
    owner = create_test_admin(tenant=Tenant.legacy_default())
    registration_ref = issue_registration_ref(owner)
    monkeypatch.setattr("apps.users.views.verify_and_consume", lambda *args, **kwargs: True)
    client, token = csrf_client()
    session = client.session
    session["before_registration"] = True
    session.save()
    client.cookies["xianwen_session"] = session.session_key
    old_session_key = session.session_key

    response = post_with_csrf(
        client,
        REGISTER_PATH,
        token,
        {
            "phone": "0086 138-0013-8000",
            "nickname": "  新用户  ",
            "sms_code": "438921",
            "password": STRONG_PASSWORD,
            "ref": registration_ref,
        },
    )

    assert response.status_code == 201
    user = User.objects.get(phone="+8613800138000")
    assert user.phone == "+8613800138000"
    assert user.nickname == "新用户"
    assert user.approval_status == User.ApprovalStatus.APPROVED
    assert user.account_status == User.AccountStatus.ACTIVE
    assert user.approved_at is not None
    assert user.approved_by is None
    assert user.is_active is True
    assert user.password != STRONG_PASSWORD
    assert user.check_password(STRONG_PASSWORD)
    assert response.json()["data"] == {
        "id": str(user.id),
        "nickname": "新用户",
        "phone_masked": "+86 138****8000",
        "approval_status": "approved",
        "account_status": "active",
        "commercial_identity": "USER",
        "home_route": "/workspace",
        "tenant": {
            "id": "00000000-0000-4000-8000-000000000001",
            "key": "legacy-default",
            "display_name": "默认租户",
            "brand_name": "显问 GEO",
            "logo_reference": "",
        },
    }
    assert response.json()["request_id"] == response["X-Request-ID"]
    assert response.cookies["xianwen_session"].value != old_session_key
    assert client.get(ME_PATH).status_code == 200

    assert client.session[SESSION_VERSION_KEY] == user.session_version


@pytest.mark.django_db
def test_duplicate_phone_is_only_revealed_after_valid_code(monkeypatch):
    create_user()
    registration_ref = valid_registration_ref()
    client, token = csrf_client()
    monkeypatch.setattr("apps.users.views.verify_and_consume", lambda *args, **kwargs: False)
    invalid = post_with_csrf(
        client,
        REGISTER_PATH,
        token,
        {
            "phone": "13800138000",
            "nickname": "重复用户",
            "sms_code": "000000",
            "password": STRONG_PASSWORD,
            "ref": registration_ref,
        },
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "VERIFICATION_CODE_INVALID"

    monkeypatch.setattr("apps.users.views.verify_and_consume", lambda *args, **kwargs: True)
    conflict = post_with_csrf(
        client,
        REGISTER_PATH,
        token,
        {
            "phone": "13800138000",
            "nickname": "重复用户",
            "sms_code": "438921",
            "password": STRONG_PASSWORD,
            "ref": registration_ref,
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"] == {
        "code": "ACCOUNT_ALREADY_EXISTS",
        "message": "该手机号已注册，请登录或找回密码",
        "details": {},
    }
    assert User.objects.filter(is_staff=False, is_superuser=False).count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize("nickname", ["   ", "含\x00控制符", "x" * 51])
def test_registration_rejects_invalid_nickname_without_consuming_code(monkeypatch, nickname):
    consumed = False

    def consume(*args, **kwargs):
        nonlocal consumed
        consumed = True
        return True

    monkeypatch.setattr("apps.users.views.verify_and_consume", consume)
    registration_ref = valid_registration_ref()
    client, token = csrf_client()
    response = post_with_csrf(
        client,
        REGISTER_PATH,
        token,
        {
            "phone": "13800138000",
            "nickname": nickname,
            "sms_code": "438921",
            "password": STRONG_PASSWORD,
            "ref": registration_ref,
        },
    )

    assert response.status_code == 422
    assert consumed is False
    assert User.objects.filter(is_staff=False, is_superuser=False).count() == 0


@pytest.mark.django_db
def test_registration_database_failure_does_not_retry_consumption(monkeypatch):
    calls = 0

    def consume(*args, **kwargs):
        nonlocal calls
        calls += 1
        return True

    monkeypatch.setattr("apps.users.views.verify_and_consume", consume)
    monkeypatch.setattr(
        "apps.users.views.create_registered_user",
        lambda **kwargs: (_ for _ in ()).throw(DatabaseError("private database detail")),
    )
    client, token = csrf_client()
    registration_ref = valid_registration_ref()
    client.raise_request_exception = False
    response = post_with_csrf(
        client,
        REGISTER_PATH,
        token,
        {
            "phone": "13800138000",
            "nickname": "失败用户",
            "sms_code": "438921",
            "password": STRONG_PASSWORD,
            "ref": registration_ref,
        },
    )

    assert calls == 1
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "private database detail" not in response.content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("approval_status", "account_status", "expected_status"),
    [
        (User.ApprovalStatus.PENDING, User.AccountStatus.ACTIVE, 200),
        (User.ApprovalStatus.APPROVED, User.AccountStatus.ACTIVE, 200),
        (User.ApprovalStatus.REJECTED, User.AccountStatus.ACTIVE, 200),
        (User.ApprovalStatus.PENDING, User.AccountStatus.CANCEL_PENDING, 200),
        (User.ApprovalStatus.PENDING, User.AccountStatus.FROZEN, 403),
        (User.ApprovalStatus.PENDING, User.AccountStatus.CANCELLED, 403),
    ],
)
def test_sms_login_respects_account_but_not_approval_status(
    monkeypatch, approval_status, account_status, expected_status
):
    user = create_user(approval_status=approval_status, account_status=account_status)
    assign_test_customer(user)
    monkeypatch.setattr("apps.users.views.verify_and_consume", lambda *args, **kwargs: True)
    client, token = csrf_client()
    response = post_with_csrf(
        client,
        SMS_LOGIN_PATH,
        token,
        {"phone": "13800138000", "sms_code": "438921"},
    )

    assert response.status_code == expected_status
    event = LoginEvent.objects.get()
    assert event.login_method == LoginEvent.LoginMethod.SMS
    if expected_status == 200:
        assert event.success is True
        assert client.session[SESSION_VERSION_KEY] == user.session_version
        assert response.json()["data"]["id"] == str(user.id)
        assert client.get(ME_PATH).status_code == 200
    else:
        assert response.json()["error"]["code"] == "ACCOUNT_UNAVAILABLE"
        assert event.success is False
        assert client.get(ME_PATH).status_code == 401


@pytest.mark.django_db
def test_invalid_sms_code_and_unknown_user_have_same_external_response(monkeypatch):
    client, token = csrf_client()
    monkeypatch.setattr("apps.users.views.verify_and_consume", lambda *args, **kwargs: False)
    invalid = post_with_csrf(
        client,
        SMS_LOGIN_PATH,
        token,
        {"phone": "13800138000", "sms_code": "000000"},
    )
    monkeypatch.setattr("apps.users.views.verify_and_consume", lambda *args, **kwargs: True)
    unknown_client, unknown_token = csrf_client()
    unknown = post_with_csrf(
        unknown_client,
        SMS_LOGIN_PATH,
        unknown_token,
        {"phone": "13900139000", "sms_code": "438921"},
    )

    for response in (invalid, unknown):
        assert response.status_code == 401
        assert response.json()["error"] == {
            "code": "AUTH_CREDENTIALS_INVALID",
            "message": "手机号或短信验证码不正确",
            "details": {},
        }


@pytest.mark.django_db
def test_sms_login_event_failure_revokes_new_session(monkeypatch):
    assign_test_customer(create_user())
    monkeypatch.setattr("apps.users.views.verify_and_consume", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        "apps.users.views.record_login_event",
        lambda **kwargs: (_ for _ in ()).throw(DatabaseError("event failure")),
    )
    client, token = csrf_client()
    client.raise_request_exception = False
    response = post_with_csrf(
        client,
        SMS_LOGIN_PATH,
        token,
        {"phone": "13800138000", "sms_code": "438921"},
    )

    assert response.status_code == 500
    assert client.get(ME_PATH).status_code == 401


@pytest.mark.django_db
def test_password_reset_invalidates_two_existing_sessions(monkeypatch):
    user = create_user()
    assign_test_customer(user)
    first, first_token = csrf_client()
    second, second_token = csrf_client()
    assert password_login(first, first_token).status_code == 200
    assert password_login(second, second_token).status_code == 200
    assert first.get(ME_PATH).status_code == 200
    assert second.get(ME_PATH).status_code == 200

    monkeypatch.setattr("apps.users.views.verify_and_consume", lambda *args, **kwargs: True)
    reset_client, reset_token = csrf_client()
    response = post_with_csrf(
        reset_client,
        PASSWORD_RESET_PATH,
        reset_token,
        {
            "phone": "13800138000",
            "sms_code": "438921",
            "new_password": NEW_PASSWORD,
        },
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"reset": True}
    user.refresh_from_db()
    assert not user.check_password(STRONG_PASSWORD)
    assert user.check_password(NEW_PASSWORD)
    assert first.get(ME_PATH).status_code == 401
    assert second.get(ME_PATH).status_code == 401
    assert reset_client.get(ME_PATH).status_code == 401


@pytest.mark.django_db
@pytest.mark.parametrize("account_status", [None, User.AccountStatus.CANCELLED])
def test_password_reset_unknown_or_cancelled_is_generic_success(monkeypatch, account_status):
    if account_status:
        user = create_user(account_status=account_status)
        original_password = user.password
    monkeypatch.setattr("apps.users.views.verify_and_consume", lambda *args, **kwargs: True)
    client, token = csrf_client()
    response = post_with_csrf(
        client,
        PASSWORD_RESET_PATH,
        token,
        {
            "phone": "13800138000",
            "sms_code": "438921",
            "new_password": NEW_PASSWORD,
        },
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"reset": True}
    if account_status:
        user.refresh_from_db()
        assert user.password == original_password
    else:
        assert User.objects.count() == 0


@pytest.mark.django_db
def test_frozen_user_can_reset_but_remains_unavailable(monkeypatch):
    user = create_user(account_status=User.AccountStatus.FROZEN)
    monkeypatch.setattr("apps.users.views.verify_and_consume", lambda *args, **kwargs: True)
    client, token = csrf_client()
    response = post_with_csrf(
        client,
        PASSWORD_RESET_PATH,
        token,
        {
            "phone": "13800138000",
            "sms_code": "438921",
            "new_password": NEW_PASSWORD,
        },
    )

    assert response.status_code == 200
    user.refresh_from_db()
    assert user.check_password(NEW_PASSWORD)
    assert user.account_status == User.AccountStatus.FROZEN
    assert user.is_active is False


@pytest.mark.django_db
def test_submission_failure_limits_are_isolated_and_only_count_invalid_credentials(
    monkeypatch, settings
):
    settings.LOGIN_RATE_LIMIT_COMBINATION_FAILURES = 2
    settings.LOGIN_RATE_LIMIT_PHONE_FAILURES = 20
    settings.LOGIN_RATE_LIMIT_IP_FAILURES = 20
    monkeypatch.setattr("apps.users.views.verify_and_consume", lambda *args, **kwargs: False)
    client, token = csrf_client()
    payload = {"phone": "13800138000", "sms_code": "000000"}
    registration_ref = valid_registration_ref()

    first = post_with_csrf(client, SMS_LOGIN_PATH, token, payload)
    second = post_with_csrf(client, SMS_LOGIN_PATH, token, payload)
    register = post_with_csrf(
        client,
        REGISTER_PATH,
        token,
        {
            **payload,
            "nickname": "隔离用户",
            "password": STRONG_PASSWORD,
            "ref": registration_ref,
        },
    )
    malformed = post_with_csrf(
        client,
        REGISTER_PATH,
        token,
        {"phone": "bad", "nickname": "表单错误", "sms_code": "", "password": "short"},
    )

    assert first.status_code == 401
    assert second.status_code == 429
    assert register.status_code == 422
    assert register.json()["error"]["code"] == "VERIFICATION_CODE_INVALID"
    assert malformed.status_code == 422
    assert malformed.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.django_db
def test_service_unavailable_does_not_consume_submission_failure_limit(monkeypatch, settings):
    settings.LOGIN_RATE_LIMIT_COMBINATION_FAILURES = 2
    settings.LOGIN_RATE_LIMIT_PHONE_FAILURES = 20
    settings.LOGIN_RATE_LIMIT_IP_FAILURES = 20
    calls = 0

    def verify(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise SmsServiceUnavailable
        return False

    monkeypatch.setattr("apps.users.views.verify_and_consume", verify)
    client, token = csrf_client()
    payload = {"phone": "13800138000", "sms_code": "000000"}

    unavailable = post_with_csrf(client, SMS_LOGIN_PATH, token, payload)
    invalid = post_with_csrf(client, SMS_LOGIN_PATH, token, payload)

    assert unavailable.status_code == 503
    assert invalid.status_code == 401


@pytest.mark.django_db
def test_success_clears_combination_submission_failures(monkeypatch, settings):
    assign_test_customer(create_user())
    settings.LOGIN_RATE_LIMIT_COMBINATION_FAILURES = 2
    settings.LOGIN_RATE_LIMIT_PHONE_FAILURES = 20
    settings.LOGIN_RATE_LIMIT_IP_FAILURES = 20
    outcomes = iter([False, True, False])
    monkeypatch.setattr(
        "apps.users.views.verify_and_consume", lambda *args, **kwargs: next(outcomes)
    )

    first, token = csrf_client()
    payload = {"phone": "13800138000", "sms_code": "438921"}
    assert post_with_csrf(first, SMS_LOGIN_PATH, token, payload).status_code == 401

    success, success_token = csrf_client()
    assert post_with_csrf(success, SMS_LOGIN_PATH, success_token, payload).status_code == 200

    third, third_token = csrf_client()
    assert post_with_csrf(third, SMS_LOGIN_PATH, third_token, payload).status_code == 401


@pytest.mark.django_db
def test_auth_responses_and_logs_do_not_expose_secrets(monkeypatch, caplog):
    create_user()
    monkeypatch.setattr("apps.users.views.verify_and_consume", lambda *args, **kwargs: False)
    client, token = csrf_client()
    registration_ref = valid_registration_ref()
    secrets = ["438921", "13800138000", STRONG_PASSWORD, token, registration_ref]
    with caplog.at_level(logging.INFO):
        response = post_with_csrf(
            client,
            REGISTER_PATH,
            token,
            {
                "phone": "13800138000",
                "nickname": "安全用户",
                "sms_code": "438921",
                "password": STRONG_PASSWORD,
                "ref": registration_ref,
            },
        )
    combined = response.content.decode() + caplog.text
    for secret in secrets:
        assert secret not in combined
