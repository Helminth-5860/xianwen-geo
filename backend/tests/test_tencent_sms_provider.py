from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from django.conf import settings
from requests import ConnectionError, Timeout
from tencentcloud.common.exception.tencent_cloud_sdk_exception import (  # type: ignore[import-untyped]
    TencentCloudSDKException,
)

from apps.users.sms.exceptions import SmsServiceUnavailable
from apps.users.sms.providers import (
    MockSmsProvider,
    UnavailableSmsProvider,
    _provider_for_name,
    get_sms_provider,
)
from apps.users.sms.purposes import SmsPurpose
from apps.users.sms.service import send_verification_code
from apps.users.sms.tencent import (
    TEMPLATE_SETTING_BY_PURPOSE,
    TENCENT_SMS_API_VERSION,
    TENCENT_SMS_ENDPOINT,
    NoopRetryer,
    SmsProviderError,
    SmsProviderErrorCategory,
    TencentSmsConfig,
    TencentSmsProvider,
    _default_client_factory,
)
from tests.sms_fakes import MemorySmsStore

COMPLETE_SETTINGS = {
    "SMS_PROVIDER": "tencent",
    "ENABLE_REAL_SMS": True,
    "SMS_REGION": "ap-beijing",
    "SMS_APP_ID": "1400000000",
    "SMS_SECRET_ID": "test-secret-id-must-not-leak",
    "SMS_SECRET_KEY": "test-secret-key-must-not-leak",
    "SMS_SIGN_NAME": "先问测试签名",
    "SMS_TEMPLATE_REGISTER": "100001",
    "SMS_TEMPLATE_LOGIN": "100002",
    "SMS_TEMPLATE_SECURITY": "100003",
    "SMS_TEMPLATE_REVIEW": "100004",
    "SMS_TEMPLATE_PLAN_EXPIRY": "100005",
    "SMS_PROVIDER_TIMEOUT_SECONDS": 10,
}


class FakeClient:
    def __init__(self, *, response=None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.requests = []

    def SendSms(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.response


@pytest.fixture(autouse=True)
def clear_provider_cache():
    _provider_for_name.cache_clear()
    yield
    _provider_for_name.cache_clear()


def config(**overrides) -> TencentSmsConfig:
    values = {
        "secret_id": "test-secret-id-must-not-leak",
        "secret_key": "test-secret-key-must-not-leak",
        "app_id": "1400000000",
        "sign_name": "先问测试签名",
        "region": "ap-beijing",
        "timeout_seconds": 10,
        "template_ids": {
            SmsPurpose.REGISTER: "100001",
            SmsPurpose.LOGIN: "100002",
            SmsPurpose.PASSWORD_RESET: "100003",
            SmsPurpose.PHONE_CHANGE: "100003",
            SmsPurpose.ADMIN_STEP_UP: "100003",
        },
    }
    values.update(overrides)
    return TencentSmsConfig(**values)


def success_response(phone: str = "+8613800138000"):
    return SimpleNamespace(
        SendStatusSet=[SimpleNamespace(Code="Ok", PhoneNumber=phone)],
        RequestId="safe-request-id",
    )


def provider_with(client: FakeClient, **config_overrides) -> TencentSmsProvider:
    return TencentSmsProvider(
        config(**config_overrides),
        client_factory=lambda _: client,
    )


@pytest.mark.parametrize("purpose", list(TEMPLATE_SETTING_BY_PURPOSE))
def test_purpose_template_mapping_is_frozen(purpose):
    client = FakeClient(response=success_response())
    provider = provider_with(client)

    provider.send_verification_code(
        phone="+8613800138000",
        purpose=purpose,
        code="492731",
        expires_in=300,
    )

    request = client.requests[0]
    assert request.TemplateId == config().template_ids[purpose]
    assert (
        TEMPLATE_SETTING_BY_PURPOSE[purpose]
        == {
            SmsPurpose.REGISTER: "SMS_TEMPLATE_REGISTER",
            SmsPurpose.LOGIN: "SMS_TEMPLATE_LOGIN",
            SmsPurpose.PASSWORD_RESET: "SMS_TEMPLATE_SECURITY",
            SmsPurpose.PHONE_CHANGE: "SMS_TEMPLATE_SECURITY",
            SmsPurpose.ADMIN_STEP_UP: "SMS_TEMPLATE_SECURITY",
        }[purpose]
    )


@pytest.mark.parametrize(
    ("expires_in", "expiry_minutes"),
    [(1, "1"), (59, "1"), (60, "1"), (61, "2"), (300, "5")],
)
def test_request_contract_and_expiry_round_up(expires_in, expiry_minutes):
    client = FakeClient(response=success_response())
    provider = provider_with(client)

    provider.send_verification_code(
        phone="+8613800138000",
        purpose=SmsPurpose.LOGIN,
        code="492731",
        expires_in=expires_in,
    )

    assert len(client.requests) == 1
    request = client.requests[0]
    assert request.PhoneNumberSet == ["+8613800138000"]
    assert request.SmsSdkAppId == "1400000000"
    assert request.SignName == "先问测试签名"
    assert request.TemplateParamSet == ["492731", expiry_minutes]
    assert request.SessionContext == ""
    assert request.ExtendCode == ""
    assert request.SenderId == ""


def test_service_passes_normalized_e164_phone_to_tencent_request(monkeypatch):
    client = FakeClient(response=success_response())
    provider = provider_with(client)
    monkeypatch.setattr(
        "apps.users.sms.service.generate_verification_code",
        lambda: "492731",
    )

    send_verification_code(
        "13800138000",
        SmsPurpose.LOGIN,
        "192.0.2.1",
        provider=provider,
        store=MemorySmsStore(),
    )

    assert client.requests[0].PhoneNumberSet == ["+8613800138000"]


def test_factory_selects_tencent_when_real_sms_is_enabled(settings):
    for name, value in COMPLETE_SETTINGS.items():
        setattr(settings, name, value)

    provider = get_sms_provider()

    assert isinstance(provider, TencentSmsProvider)
    assert provider.locally_available is True


def test_unsupported_provider_still_fails_closed(settings):
    settings.SMS_PROVIDER = "unsupported-provider"

    assert isinstance(get_sms_provider(), UnavailableSmsProvider)


@pytest.mark.parametrize(
    "missing",
    [
        "SMS_SECRET_ID",
        "SMS_SECRET_KEY",
        "SMS_APP_ID",
        "SMS_SIGN_NAME",
        "SMS_REGION",
        "SMS_TEMPLATE_REGISTER",
        "SMS_TEMPLATE_LOGIN",
        "SMS_TEMPLATE_SECURITY",
    ],
)
def test_missing_required_tencent_setting_fails_with_name_only(settings, missing):
    for name, value in COMPLETE_SETTINGS.items():
        setattr(settings, name, value)
    setattr(settings, missing, "")

    with pytest.raises(SmsProviderError) as failure:
        TencentSmsProvider.from_settings(client_factory=lambda _: FakeClient())

    assert failure.value.category == SmsProviderErrorCategory.INVALID_CONFIGURATION
    assert failure.value.provider_code == missing
    assert str(failure.value) == ""


def test_real_provider_never_activates_when_enable_real_sms_is_false(settings):
    for name, value in COMPLETE_SETTINGS.items():
        setattr(settings, name, value)
    settings.ENABLE_REAL_SMS = False

    with pytest.raises(SmsProviderError) as failure:
        get_sms_provider()

    assert failure.value.provider_code == "ENABLE_REAL_SMS"


def test_default_sdk_client_uses_fixed_endpoint_region_post_timeout_and_no_retry(monkeypatch):
    captured = {}

    class FakeCredential:
        def __init__(self, secret_id, secret_key):
            captured["credential"] = (secret_id, secret_key)

    class FakeSdkClient:
        def __init__(self, configured_credential, region, profile):
            captured["client"] = (configured_credential, region, profile)

    monkeypatch.setattr("apps.users.sms.tencent.credential.Credential", FakeCredential)
    monkeypatch.setattr("apps.users.sms.tencent.sms_client.SmsClient", FakeSdkClient)

    built = _default_client_factory(config())

    assert isinstance(built, FakeSdkClient)
    assert captured["credential"] == (
        "test-secret-id-must-not-leak",
        "test-secret-key-must-not-leak",
    )
    _, region, profile = captured["client"]
    assert region == "ap-beijing"
    assert profile.httpProfile.protocol == "https"
    assert profile.httpProfile.endpoint == TENCENT_SMS_ENDPOINT
    assert profile.httpProfile.reqMethod == "POST"
    assert profile.httpProfile.reqTimeout == 10
    assert isinstance(profile.retryer, NoopRetryer)
    assert TENCENT_SMS_API_VERSION == "2021-01-11"


def test_code_ok_is_the_only_success_status():
    client = FakeClient(response=success_response())
    provider_with(client).send_verification_code(
        phone="+8613800138000",
        purpose=SmsPurpose.LOGIN,
        code="492731",
        expires_in=300,
    )
    assert len(client.requests) == 1


@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(SendStatusSet=None, RequestId="safe-request-id"),
        SimpleNamespace(SendStatusSet=[], RequestId="safe-request-id"),
        SimpleNamespace(
            SendStatusSet=[
                SimpleNamespace(Code="Ok", PhoneNumber="+8613800138000"),
                SimpleNamespace(Code="Ok", PhoneNumber="+8613800138001"),
            ],
            RequestId="safe-request-id",
        ),
        SimpleNamespace(
            SendStatusSet=[SimpleNamespace(Code=None, PhoneNumber="+8613800138000")],
            RequestId="safe-request-id",
        ),
        SimpleNamespace(
            SendStatusSet=[SimpleNamespace(Code="Ok", PhoneNumber="+8613800138999")],
            RequestId="safe-request-id",
        ),
    ],
)
def test_empty_or_malformed_send_status_fails_closed(response):
    with pytest.raises(SmsProviderError) as failure:
        provider_with(FakeClient(response=response)).send_verification_code(
            phone="+8613800138000",
            purpose=SmsPurpose.LOGIN,
            code="492731",
            expires_in=300,
        )

    assert failure.value.category == SmsProviderErrorCategory.UNKNOWN_PROVIDER_FAILURE


def test_non_ok_send_status_fails_closed_with_safe_category():
    response = SimpleNamespace(
        SendStatusSet=[
            SimpleNamespace(
                Code="FailedOperation.TemplateIncorrectOrUnapproved",
                Message="raw provider message with 492731 must not leak",
                PhoneNumber="+8613800138000",
            )
        ],
        RequestId="safe-request-id",
    )

    with pytest.raises(SmsProviderError) as failure:
        provider_with(FakeClient(response=response)).send_verification_code(
            phone="+8613800138000",
            purpose=SmsPurpose.LOGIN,
            code="492731",
            expires_in=300,
        )

    assert failure.value.category == SmsProviderErrorCategory.TEMPLATE_OR_SIGN
    assert failure.value.provider_code == "FailedOperation.TemplateIncorrectOrUnapproved"
    assert "492731" not in str(failure.value)
    assert "raw provider" not in repr(failure.value)


@pytest.mark.parametrize(
    ("provider_code", "category"),
    [
        ("AuthFailure.SecretIdNotFound", SmsProviderErrorCategory.AUTH_OR_PERMISSION),
        ("UnauthorizedOperation", SmsProviderErrorCategory.AUTH_OR_PERMISSION),
        ("RequestLimitExceeded", SmsProviderErrorCategory.RATE_OR_QUOTA),
        ("LimitExceeded.PhoneNumberDailyLimit", SmsProviderErrorCategory.RATE_OR_QUOTA),
        ("InvalidParameterValue.PhoneNumber", SmsProviderErrorCategory.INVALID_REQUEST),
        (
            "FailedOperation.SignatureIncorrectOrUnapproved",
            SmsProviderErrorCategory.TEMPLATE_OR_SIGN,
        ),
        ("InternalError", SmsProviderErrorCategory.PROVIDER_UNAVAILABLE),
        ("ResourceUnavailable", SmsProviderErrorCategory.PROVIDER_UNAVAILABLE),
        ("ServiceUnavailable", SmsProviderErrorCategory.PROVIDER_UNAVAILABLE),
        ("Unknown.ProviderCode", SmsProviderErrorCategory.UNKNOWN_PROVIDER_FAILURE),
    ],
)
def test_tencent_sdk_errors_are_normalized_without_message_leak(provider_code, category):
    sensitive = "otp=492731 phone=+8613800138000 secret=test-secret-key-must-not-leak"
    client = FakeClient(error=TencentCloudSDKException(provider_code, sensitive, "safe-request-id"))

    with pytest.raises(SmsProviderError) as failure:
        provider_with(client).send_verification_code(
            phone="+8613800138000",
            purpose=SmsPurpose.LOGIN,
            code="492731",
            expires_in=300,
        )

    assert failure.value.category == category
    assert len(client.requests) == 1
    assert sensitive not in str(failure.value)
    assert sensitive not in repr(failure.value)


@pytest.mark.parametrize(
    ("error", "category"),
    [
        (Timeout("raw timeout 492731"), SmsProviderErrorCategory.PROVIDER_TIMEOUT),
        (TimeoutError("raw timeout 492731"), SmsProviderErrorCategory.PROVIDER_TIMEOUT),
        (ConnectionError("raw network 492731"), SmsProviderErrorCategory.PROVIDER_NETWORK),
        (
            TencentCloudSDKException("ClientNetworkError", "read timed out 492731"),
            SmsProviderErrorCategory.PROVIDER_TIMEOUT,
        ),
        (
            TencentCloudSDKException("ClientNetworkError", "connection refused 492731"),
            SmsProviderErrorCategory.PROVIDER_NETWORK,
        ),
    ],
)
def test_timeout_and_network_fail_closed_with_exactly_one_attempt(error, category):
    client = FakeClient(error=error)

    with pytest.raises(SmsProviderError) as failure:
        provider_with(client).send_verification_code(
            phone="+8613800138000",
            purpose=SmsPurpose.LOGIN,
            code="492731",
            expires_in=300,
        )

    assert failure.value.category == category
    assert len(client.requests) == 1


def test_provider_failure_never_falls_back_to_mock(monkeypatch):
    failing = provider_with(FakeClient(error=Timeout("ambiguous provider timeout")))
    mock = MockSmsProvider()
    monkeypatch.setattr("apps.users.sms.providers.MockSmsProvider", lambda: mock)

    with pytest.raises(SmsServiceUnavailable):
        send_verification_code(
            "13800138000",
            SmsPurpose.LOGIN,
            "192.0.2.1",
            provider=failing,
            store=MemorySmsStore(),
        )

    assert mock.outbox == ()


def test_sensitive_values_are_absent_from_logs_and_safe_exception(caplog):
    sensitive_values = (
        "492731",
        "+8613800138000",
        "test-secret-id-must-not-leak",
        "test-secret-key-must-not-leak",
    )
    error = TencentCloudSDKException(
        "AuthFailure.SecretIdNotFound",
        " ".join(sensitive_values),
        "safe-request-id",
    )

    with caplog.at_level(logging.DEBUG), pytest.raises(SmsProviderError) as failure:
        provider_with(FakeClient(error=error)).send_verification_code(
            phone=sensitive_values[1],
            purpose=SmsPurpose.LOGIN,
            code=sensitive_values[0],
            expires_in=300,
        )

    combined = caplog.text + str(failure.value) + repr(failure.value)
    for sensitive in sensitive_values:
        assert sensitive not in combined


def test_existing_sms_challenge_security_defaults_are_unchanged():
    assert settings.SMS_CODE_TTL_SECONDS == 300
    assert settings.SMS_RESEND_COOLDOWN_SECONDS == 60
    assert settings.SMS_MAX_ATTEMPTS == 5
    assert settings.SMS_PROVIDER_TIMEOUT_SECONDS == 10


def test_tencent_sdk_raw_request_logger_is_suppressed():
    from apps.core.logging import build_logging_config

    sdk_logger = build_logging_config("production")["loggers"]["tencentcloud_sdk_common"]
    assert sdk_logger == {
        "handlers": [],
        "level": "CRITICAL",
        "propagate": False,
    }
