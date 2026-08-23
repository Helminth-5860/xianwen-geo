from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.users.authentication import SESSION_VERSION_KEY
from apps.users.models import LoginEvent, User
from tests.customer_ownership_helpers import assign_test_customer

STRONG_PASSWORD = "Correct-Horse-Battery-2026!"
LOGIN_PATH = "/api/v1/auth/login/password"
CSRF_PATH = "/api/v1/auth/csrf"
LOGOUT_PATH = "/api/v1/auth/logout"
ME_PATH = "/api/v1/me"


@pytest.fixture(autouse=True)
def clear_auth_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def user(db):
    created = User.objects.create_user(
        phone="13800138000",
        nickname="认证用户",
        password=STRONG_PASSWORD,
    )
    assign_test_customer(created)
    return created


def csrf_client():
    client = APIClient(enforce_csrf_checks=True)
    response = client.get(CSRF_PATH)
    assert response.status_code == 200
    return client, response.json()["data"]["csrf_token"], response


def password_login(client, csrf_token, *, phone="13800138000", password=STRONG_PASSWORD):
    return client.post(
        LOGIN_PATH,
        data={"phone": phone, "password": password},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )


@pytest.mark.django_db
def test_csrf_endpoint_sets_readable_cookie_with_standard_envelope():
    _, token, response = csrf_client()

    assert token
    assert response.json()["success"] is True
    assert response.json()["request_id"] == response["X-Request-ID"]
    cookie = response.cookies["xianwen_csrf"]
    assert cookie.value
    assert cookie["httponly"] == ""
    assert cookie["samesite"] == "Lax"
    assert cookie["path"] == "/"


@pytest.mark.django_db
def test_password_login_rejects_missing_and_invalid_csrf_before_authentication(user):
    missing_client = APIClient(enforce_csrf_checks=True)
    missing = missing_client.post(
        LOGIN_PATH,
        data={"phone": user.phone, "password": STRONG_PASSWORD},
        format="json",
    )
    assert missing.status_code == 403
    assert missing.json()["error"]["code"] == "CSRF_FAILED"

    client, _, _ = csrf_client()
    invalid = password_login(client, "invalid-csrf-token")
    assert invalid.status_code == 403
    assert invalid.json()["error"]["code"] == "CSRF_FAILED"
    assert LoginEvent.objects.count() == 0


@pytest.mark.django_db
def test_successful_password_login_rotates_session_and_sets_browser_cookie(user):
    client, csrf_token, _ = csrf_client()
    session = client.session
    session["before_login"] = True
    session.save()
    client.cookies["xianwen_session"] = session.session_key
    previous_session_key = session.session_key

    response = password_login(client, csrf_token, phone="0086 138-0013-8000")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "id": str(user.id),
        "nickname": "认证用户",
        "phone_masked": "+86 138****8000",
        "approval_status": "pending",
        "account_status": "active",
        "commercial_identity": "USER",
        "home_route": "/workspace",
        "tenant": None,
    }
    session_cookie = response.cookies["xianwen_session"]
    assert session_cookie.value != previous_session_key
    assert session_cookie["httponly"] is True
    assert session_cookie["samesite"] == "Lax"
    assert session_cookie["path"] == "/"
    assert session_cookie["domain"] == ""
    assert session_cookie["expires"] == ""
    assert session_cookie["max-age"] == ""

    authenticated_session = client.session
    assert authenticated_session.get_expire_at_browser_close() is True
    expiry_delta = authenticated_session.get_expiry_date() - timezone.now()
    assert timedelta(hours=11, minutes=59) <= expiry_delta <= timedelta(hours=12)
    assert LoginEvent.objects.get().success is True
    assert authenticated_session[SESSION_VERSION_KEY] == user.session_version


@pytest.mark.django_db
def test_login_event_failure_does_not_leave_authenticated_session(user, monkeypatch):
    def fail_to_record_login_event(**kwargs):
        raise RuntimeError("audit storage unavailable")

    monkeypatch.setattr(
        "apps.users.views.record_password_login_event",
        fail_to_record_login_event,
    )
    client, csrf_token, _ = csrf_client()
    client.raise_request_exception = False

    response = password_login(client, csrf_token)

    assert response.status_code == 500
    assert response.json()["error"] == {
        "code": "INTERNAL_ERROR",
        "message": "服务器内部错误",
        "details": {},
    }
    assert client.get(ME_PATH).status_code == 401


@pytest.mark.django_db
def test_production_session_cookie_is_secure(user, settings):
    settings.SESSION_COOKIE_SECURE = True
    settings.CSRF_COOKIE_SECURE = True
    client, csrf_token, csrf_response = csrf_client()

    response = password_login(client, csrf_token)

    assert response.status_code == 200
    assert csrf_response.cookies["xianwen_csrf"]["secure"] is True
    assert response.cookies["xianwen_session"]["secure"] is True


@pytest.mark.django_db
def test_wrong_password_and_unknown_phone_have_identical_external_response(user):
    wrong_client, wrong_token, _ = csrf_client()
    wrong = password_login(wrong_client, wrong_token, password="Wrong-Password-2026!")

    unknown_client, unknown_token, _ = csrf_client()
    unknown = password_login(
        unknown_client,
        unknown_token,
        phone="13900139000",
        password="Wrong-Password-2026!",
    )

    for response in (wrong, unknown):
        assert response.status_code == 401
        assert response.json()["error"] == {
            "code": "AUTH_REQUIRED",
            "message": "手机号或密码不正确",
            "details": {},
        }


@pytest.mark.django_db
@pytest.mark.parametrize(
    "approval_status",
    [
        User.ApprovalStatus.PENDING,
        User.ApprovalStatus.APPROVED,
        User.ApprovalStatus.REJECTED,
    ],
)
def test_approval_status_does_not_prevent_login(approval_status):
    created = User.objects.create_user(
        phone="13800138000",
        nickname="审核状态用户",
        password=STRONG_PASSWORD,
        approval_status=approval_status,
    )
    assign_test_customer(created)
    client, token, _ = csrf_client()

    assert password_login(client, token).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("account_status", "expected_status"),
    [
        (User.AccountStatus.ACTIVE, 200),
        (User.AccountStatus.CANCEL_PENDING, 200),
        (User.AccountStatus.FROZEN, 401),
        (User.AccountStatus.CANCELLED, 401),
    ],
)
def test_account_status_controls_login(account_status, expected_status):
    created = User.objects.create_user(
        phone="13800138000",
        nickname="账号状态用户",
        password=STRONG_PASSWORD,
        account_status=account_status,
    )
    assign_test_customer(created)
    client, token, _ = csrf_client()

    response = password_login(client, token)

    assert response.status_code == expected_status
    if expected_status == 401:
        assert response.json()["error"]["message"] == "手机号或密码不正确"


@pytest.mark.django_db
def test_me_requires_session_and_returns_minimum_user_data(user):
    anonymous = APIClient().get(ME_PATH)
    assert anonymous.status_code == 401
    assert anonymous.json()["error"]["code"] == "AUTH_REQUIRED"

    client, token, _ = csrf_client()
    assert password_login(client, token).status_code == 200
    response = client.get(ME_PATH)

    assert response.status_code == 200
    assert set(response.json()["data"]) == {
        "id",
        "nickname",
        "phone_masked",
        "approval_status",
        "account_status",
        "commercial_identity",
        "home_route",
        "tenant",
    }
    assert user.phone not in response.content.decode()


@pytest.mark.django_db
def test_logout_requires_csrf_and_invalidates_current_session(user):
    client, token, _ = csrf_client()
    assert password_login(client, token).status_code == 200

    missing_csrf = client.post(LOGOUT_PATH, data={}, format="json")
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["error"]["code"] == "CSRF_FAILED"
    assert client.get(ME_PATH).status_code == 200
    rotated_token = client.cookies["xianwen_csrf"].value

    response = client.post(
        LOGOUT_PATH,
        data={},
        format="json",
        HTTP_X_CSRFTOKEN=rotated_token,
    )
    assert response.status_code == 200
    assert response.json()["data"] == {"logged_out": True}
    assert response.json()["request_id"] == response["X-Request-ID"]
    assert client.get(ME_PATH).status_code == 401
