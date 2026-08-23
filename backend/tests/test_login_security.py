import logging

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.core.logging import RequestContextFilter
from apps.users.models import LoginEvent, User
from apps.users.rate_limits import login_rate_limit_keys
from tests.customer_ownership_helpers import assign_test_customer

STRONG_PASSWORD = "Correct-Horse-Battery-2026!"
LOGIN_PATH = "/api/v1/auth/login/password"
CSRF_PATH = "/api/v1/auth/csrf"


@pytest.fixture(autouse=True)
def clear_auth_cache():
    cache.clear()
    yield
    cache.clear()


def csrf_login_client(ip_address="127.0.0.1"):
    client = APIClient(enforce_csrf_checks=True)
    response = client.get(CSRF_PATH, REMOTE_ADDR=ip_address)
    return client, response.json()["data"]["csrf_token"]


def attempt_login(client, token, *, phone, password, ip_address="127.0.0.1"):
    return client.post(
        LOGIN_PATH,
        data={"phone": phone, "password": password},
        format="json",
        HTTP_X_CSRFTOKEN=token,
        REMOTE_ADDR=ip_address,
        HTTP_USER_AGENT="Xianwen authentication test agent",
    )


@pytest.mark.django_db
def test_combination_rate_limit_and_success_cleanup(settings):
    settings.LOGIN_RATE_LIMIT_COMBINATION_FAILURES = 2
    settings.LOGIN_RATE_LIMIT_PHONE_FAILURES = 100
    settings.LOGIN_RATE_LIMIT_IP_FAILURES = 100
    created = User.objects.create_user(
        phone="13800138000",
        nickname="限流用户",
        password=STRONG_PASSWORD,
    )
    assign_test_customer(created)
    client, token = csrf_login_client()

    first = attempt_login(
        client,
        token,
        phone="13800138000",
        password="Wrong-Password-2026!",
    )
    assert first.status_code == 401
    second = attempt_login(
        client,
        token,
        phone="13800138000",
        password="Wrong-Password-2026!",
    )
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "RATE_LIMITED"

    cache.clear()
    first_again = attempt_login(
        client,
        token,
        phone="13800138000",
        password="Wrong-Password-2026!",
    )
    assert first_again.status_code == 401
    assert (
        attempt_login(
            client,
            token,
            phone="13800138000",
            password=STRONG_PASSWORD,
        ).status_code
        == 200
    )

    client, token = csrf_login_client()
    after_success = attempt_login(
        client,
        token,
        phone="13800138000",
        password="Wrong-Password-2026!",
    )
    assert after_success.status_code == 401


@pytest.mark.django_db
def test_phone_and_ip_rate_limits_are_independent(settings):
    settings.LOGIN_RATE_LIMIT_COMBINATION_FAILURES = 100
    settings.LOGIN_RATE_LIMIT_PHONE_FAILURES = 2
    settings.LOGIN_RATE_LIMIT_IP_FAILURES = 2

    first_client, first_token = csrf_login_client("10.0.0.1")
    assert (
        attempt_login(
            first_client,
            first_token,
            phone="13800138000",
            password="Wrong-Password-2026!",
            ip_address="10.0.0.1",
        ).status_code
        == 401
    )
    second_client, second_token = csrf_login_client("10.0.0.2")
    assert (
        attempt_login(
            second_client,
            second_token,
            phone="13800138000",
            password="Wrong-Password-2026!",
            ip_address="10.0.0.2",
        ).status_code
        == 429
    )

    cache.clear()
    same_ip_client, same_ip_token = csrf_login_client("10.0.0.3")
    assert (
        attempt_login(
            same_ip_client,
            same_ip_token,
            phone="13800138000",
            password="Wrong-Password-2026!",
            ip_address="10.0.0.3",
        ).status_code
        == 401
    )
    assert (
        attempt_login(
            same_ip_client,
            same_ip_token,
            phone="13900139000",
            password="Wrong-Password-2026!",
            ip_address="10.0.0.3",
        ).status_code
        == 429
    )


@pytest.mark.django_db
def test_cache_failure_returns_generic_503(monkeypatch):
    client, token = csrf_login_client()

    def unavailable(*args, **kwargs):
        raise ConnectionError("redis unavailable with secret details")

    monkeypatch.setattr("apps.users.rate_limits.cache.get", unavailable)
    response = attempt_login(
        client,
        token,
        phone="13800138000",
        password="Wrong-Password-2026!",
    )

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "SERVICE_TEMPORARILY_UNAVAILABLE",
        "message": "服务暂时不可用",
        "details": {},
    }
    assert "redis unavailable" not in response.content.decode()


@pytest.mark.django_db
def test_login_events_are_minimal_and_do_not_store_raw_phone():
    user = User.objects.create_user(
        phone="13800138000",
        nickname="事件用户",
        password=STRONG_PASSWORD,
    )
    client, token = csrf_login_client("192.0.2.10")

    response = attempt_login(
        client,
        token,
        phone="+86 138-0013-8000",
        password="Wrong-Password-2026!",
        ip_address="192.0.2.10",
    )

    event = LoginEvent.objects.get()
    assert response.status_code == 401
    assert event.user == user
    assert event.success is False
    assert event.failure_reason == LoginEvent.FailureReason.INVALID_CREDENTIALS
    assert event.phone_fingerprint != user.phone
    assert user.phone not in event.phone_fingerprint
    assert event.ip_address == "192.0.2.10"
    assert event.request_id
    assert not hasattr(event, "password")
    assert not hasattr(event, "session_id")
    assert not hasattr(event, "cookie")


def test_rate_limit_keys_are_hmac_fingerprints(settings):
    settings.SECRET_KEY = "rate-limit-fingerprint-test-secret"
    normalized_phone = "+8613800138000"
    ip_address = "192.0.2.20"

    keys = login_rate_limit_keys(normalized_phone, ip_address)

    for fingerprint in vars(keys).values():
        assert len(fingerprint) == 64
        assert normalized_phone not in fingerprint
        assert ip_address not in fingerprint


@pytest.mark.django_db
def test_authentication_logs_do_not_include_credentials_or_session(caplog):
    created = User.objects.create_user(
        phone="13800138000",
        nickname="日志用户",
        password=STRONG_PASSWORD,
    )
    assign_test_customer(created)
    client, token = csrf_login_client()

    with caplog.at_level(logging.INFO):
        response = attempt_login(
            client,
            token,
            phone="13800138000",
            password=STRONG_PASSWORD,
        )

    assert response.status_code == 200
    log_text = caplog.text
    for secret in (
        STRONG_PASSWORD,
        "13800138000",
        "+8613800138000",
        response.cookies["xianwen_session"].value,
        token,
    ):
        assert secret not in log_text


@pytest.mark.django_db
def test_django_auth_warning_log_keeps_request_id(caplog):
    User.objects.create_user(
        phone="13800138000",
        nickname="日志关联用户",
        password=STRONG_PASSWORD,
    )
    client, token = csrf_login_client()

    with caplog.at_level(logging.WARNING):
        response = attempt_login(
            client,
            token,
            phone="13800138000",
            password="Wrong-Password-2026!",
        )

    django_request_records = [
        record for record in caplog.records if record.name == "django.request"
    ]
    assert response.status_code == 401
    assert django_request_records
    for record in django_request_records:
        RequestContextFilter().filter(record)
        assert record.request_id == response["X-Request-ID"]
