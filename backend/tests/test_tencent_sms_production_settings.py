from __future__ import annotations

import pytest

from tests.test_production_settings import import_settings

REAL_TENCENT_ENVIRONMENT = {
    "SMS_PROVIDER": "tencent",
    "ENABLE_REAL_SMS": "true",
    "SMS_REGION": "ap-beijing",
    "SMS_APP_ID": "1400000000",
    "SMS_SECRET_ID": "production-test-secret-id-value",
    "SMS_SECRET_KEY": "production-test-secret-key-value",
    "SMS_SIGN_NAME": "先问测试签名",
    "SMS_TEMPLATE_REGISTER": "100001",
    "SMS_TEMPLATE_LOGIN": "100002",
    "SMS_TEMPLATE_SECURITY": "100003",
    "SMS_TEMPLATE_REVIEW": "",
    "SMS_TEMPLATE_PLAN_EXPIRY": "",
    "SMS_PROVIDER_TIMEOUT_SECONDS": "10",
}


def test_production_accepts_complete_real_tencent_sms_configuration():
    result = import_settings(overrides=REAL_TENCENT_ENVIRONMENT)

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "missing",
    [
        "SMS_REGION",
        "SMS_APP_ID",
        "SMS_SECRET_ID",
        "SMS_SECRET_KEY",
        "SMS_SIGN_NAME",
        "SMS_TEMPLATE_REGISTER",
        "SMS_TEMPLATE_LOGIN",
        "SMS_TEMPLATE_SECURITY",
    ],
)
def test_production_real_tencent_sms_missing_configuration_fails_with_names_only(missing):
    overrides = {**REAL_TENCENT_ENVIRONMENT, missing: ""}

    result = import_settings(overrides=overrides)

    assert result.returncode != 0
    assert missing in result.stderr
    assert REAL_TENCENT_ENVIRONMENT["SMS_SECRET_ID"] not in result.stderr
    assert REAL_TENCENT_ENVIRONMENT["SMS_SECRET_KEY"] not in result.stderr


def test_production_tencent_requires_explicit_real_sms_enablement():
    result = import_settings(overrides={**REAL_TENCENT_ENVIRONMENT, "ENABLE_REAL_SMS": "false"})

    assert result.returncode != 0
    assert "ENABLE_REAL_SMS" in result.stderr


def test_production_real_sms_rejects_unsupported_provider():
    result = import_settings(overrides={**REAL_TENCENT_ENVIRONMENT, "SMS_PROVIDER": "unsupported"})

    assert result.returncode != 0
    assert "SMS_PROVIDER must be tencent" in result.stderr


@pytest.mark.parametrize("timeout", ["0", "61", "invalid"])
def test_production_tencent_timeout_is_safely_validated(timeout):
    result = import_settings(
        overrides={**REAL_TENCENT_ENVIRONMENT, "SMS_PROVIDER_TIMEOUT_SECONDS": timeout}
    )

    assert result.returncode != 0
    assert "SMS_PROVIDER_TIMEOUT_SECONDS" in result.stderr
