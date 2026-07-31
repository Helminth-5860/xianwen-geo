import logging

import pytest
from rest_framework.test import APIClient

from apps.users.sms.exceptions import SmsRateLimited, SmsServiceUnavailable
from apps.users.sms.service import SmsSendResult

CSRF_PATH = "/api/v1/auth/csrf"
SMS_SEND_PATH = "/api/v1/auth/sms/send"


def csrf_client():
    client = APIClient(enforce_csrf_checks=True)
    response = client.get(CSRF_PATH)
    return client, response.json()["data"]["csrf_token"]


@pytest.mark.django_db
def test_sms_send_requires_csrf():
    response = APIClient(enforce_csrf_checks=True).post(
        SMS_SEND_PATH,
        {"phone": "13800138000", "purpose": "register"},
        format="json",
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_FAILED"


@pytest.mark.django_db
@pytest.mark.parametrize("purpose", ["register", "login", "password_reset"])
def test_sms_send_has_identical_success_envelope(monkeypatch, purpose):
    monkeypatch.setattr(
        "apps.users.views.send_verification_code",
        lambda *args, **kwargs: SmsSendResult(expires_in=300, resend_after=60),
    )
    client, token = csrf_client()

    response = client.post(
        SMS_SEND_PATH,
        {"phone": "13800138000", "purpose": purpose},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "sent": True,
        "expires_in": 300,
        "resend_after": 60,
    }
    assert response.json()["request_id"] == response["X-Request-ID"]
    assert "code" not in response.json()["data"]


@pytest.mark.django_db
def test_change_phone_is_not_publicly_accepted():
    client, token = csrf_client()
    response = client.post(
        SMS_SEND_PATH,
        {"phone": "13800138000", "purpose": "change_phone"},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("exception", "status_code", "error_code"),
    [
        (SmsRateLimited(), 429, "RATE_LIMITED"),
        (SmsServiceUnavailable(), 503, "SERVICE_TEMPORARILY_UNAVAILABLE"),
    ],
)
def test_sms_safe_failures_are_generic(monkeypatch, exception, status_code, error_code):
    def fail(*args, **kwargs):
        raise exception

    monkeypatch.setattr("apps.users.views.send_verification_code", fail)
    client, token = csrf_client()
    response = client.post(
        SMS_SEND_PATH,
        {"phone": "13800138000", "purpose": "login"},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == error_code
    assert response.json()["error"]["details"] == {}


@pytest.mark.django_db
def test_response_and_logs_do_not_expose_sms_secrets(monkeypatch, caplog, settings):
    code = "592810"
    digest = "a" * 64
    settings.SMS_VERIFICATION_HMAC_KEY = "sensitive-hmac-key-for-log-test"

    monkeypatch.setattr(
        "apps.users.views.send_verification_code",
        lambda *args, **kwargs: SmsSendResult(expires_in=300, resend_after=60),
    )
    client, token = csrf_client()
    with caplog.at_level(logging.INFO):
        response = client.post(
            SMS_SEND_PATH,
            {"phone": "13800138000", "purpose": "register"},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )

    combined = response.content.decode() + caplog.text
    for secret in (
        code,
        digest,
        "13800138000",
        settings.SMS_VERIFICATION_HMAC_KEY,
        token,
    ):
        assert secret not in combined


@pytest.mark.django_db
def test_unconfigured_provider_returns_503_before_redis(settings):
    settings.SMS_PROVIDER = "unconfigured"
    client, token = csrf_client()

    response = client.post(
        SMS_SEND_PATH,
        {"phone": "13800138000", "purpose": "password_reset"},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "SERVICE_TEMPORARILY_UNAVAILABLE",
        "message": "服务暂时不可用",
        "details": {},
    }


@pytest.mark.django_db
def test_forged_forwarded_for_cannot_change_untrusted_client_ip(monkeypatch, settings):
    settings.TRUSTED_PROXY_HOPS = 1
    settings.TRUSTED_PROXY_NETWORKS = ()
    seen_ips = []

    def rate_by_ip(phone, purpose, ip_address):
        seen_ips.append(ip_address)
        if seen_ips.count(ip_address) > 1:
            raise SmsRateLimited
        return SmsSendResult(expires_in=300, resend_after=60)

    monkeypatch.setattr("apps.users.views.send_verification_code", rate_by_ip)
    client, token = csrf_client()
    first = client.post(
        SMS_SEND_PATH,
        {"phone": "13800138000", "purpose": "login"},
        format="json",
        HTTP_X_CSRFTOKEN=token,
        REMOTE_ADDR="192.0.2.44",
        HTTP_X_FORWARDED_FOR="203.0.113.1",
    )
    second = client.post(
        SMS_SEND_PATH,
        {"phone": "13800138000", "purpose": "login"},
        format="json",
        HTTP_X_CSRFTOKEN=token,
        REMOTE_ADDR="192.0.2.44",
        HTTP_X_FORWARDED_FOR="203.0.113.2",
    )

    assert first.status_code == 200
    assert second.status_code == 429
    assert seen_ips == ["192.0.2.44", "192.0.2.44"]


def test_mock_outbox_has_no_public_http_route():
    response = APIClient().get("/api/v1/auth/sms/outbox")

    assert response.status_code == 404
