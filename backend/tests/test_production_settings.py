import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
REQUIRED_ENVIRONMENT = {
    "APP_ENV": "production",
    "DJANGO_SETTINGS_MODULE": "config.settings",
    "DJANGO_SECRET_KEY": "x" * 64,
    "DJANGO_DEBUG": "false",
    "SMS_VERIFICATION_HMAC_KEY": "s" * 64,
    "QUOTA_IDEMPOTENCY_HMAC_KEY": "q" * 64,
    "SMS_PROVIDER": "unconfigured",
    "DATABASE_URL": "postgresql://app:placeholder@database:5432/xianwen",
    "REDIS_URL": "redis://redis:6379/0",
    "ALLOWED_HOSTS": "api.example.com",
    "CSRF_TRUSTED_ORIGINS": "https://app.example.com",
    "CORS_ALLOWED_ORIGINS": "https://app.example.com",
}


def import_settings(overrides: dict[str, str] | None = None, missing: str | None = None):
    environment = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "APP_ENV",
            "DJANGO_SETTINGS_MODULE",
            "DJANGO_SECRET_KEY",
            "DJANGO_DEBUG",
            "SMS_VERIFICATION_HMAC_KEY",
            "QUOTA_IDEMPOTENCY_HMAC_KEY",
            "SMS_PROVIDER",
            "DATABASE_URL",
            "REDIS_URL",
            "ALLOWED_HOSTS",
            "CSRF_TRUSTED_ORIGINS",
            "CORS_ALLOWED_ORIGINS",
        }
    }
    environment.update(REQUIRED_ENVIRONMENT)
    if missing:
        environment.pop(missing)
    if overrides:
        environment.update(overrides)

    return subprocess.run(
        [sys.executable, "-c", "import django; django.setup()"],
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "missing",
    [
        "DJANGO_SECRET_KEY",
        "SMS_VERIFICATION_HMAC_KEY",
        "QUOTA_IDEMPOTENCY_HMAC_KEY",
        "DATABASE_URL",
        "REDIS_URL",
        "ALLOWED_HOSTS",
        "CSRF_TRUSTED_ORIGINS",
        "CORS_ALLOWED_ORIGINS",
    ],
)
def test_production_missing_required_environment_fails_fast(missing):
    result = import_settings(missing=missing)
    assert result.returncode != 0
    assert missing in result.stderr


@pytest.mark.parametrize(
    ("overrides", "expected_error"),
    [
        ({"DJANGO_DEBUG": "true"}, "DJANGO_DEBUG must be false"),
        ({"DATABASE_URL": "sqlite:///unsafe.sqlite3"}, "SQLite is forbidden"),
        ({"ALLOWED_HOSTS": "*"}, "Wildcard ALLOWED_HOSTS"),
        ({"DJANGO_SECRET_KEY": "weak"}, "DJANGO_SECRET_KEY is too weak"),
        (
            {"SMS_VERIFICATION_HMAC_KEY": "weak"},
            "SMS_VERIFICATION_HMAC_KEY is too weak",
        ),
        (
            {"QUOTA_IDEMPOTENCY_HMAC_KEY": "weak"},
            "QUOTA_IDEMPOTENCY_HMAC_KEY is too weak",
        ),
        ({"SMS_PROVIDER": "mock"}, "Mock SMS provider is forbidden"),
        (
            {"SMS_VERIFICATION_HMAC_KEY": "x" * 64},
            "must not reuse DJANGO_SECRET_KEY",
        ),
        (
            {"QUOTA_IDEMPOTENCY_HMAC_KEY": "x" * 64},
            "must not reuse another application secret",
        ),
        (
            {"QUOTA_IDEMPOTENCY_HMAC_KEY": "s" * 64},
            "must not reuse another application secret",
        ),
    ],
)
def test_production_rejects_unsafe_configuration(overrides, expected_error):
    result = import_settings(overrides=overrides)
    assert result.returncode != 0
    assert expected_error in result.stderr


def test_production_accepts_complete_safe_configuration():
    result = import_settings()
    assert result.returncode == 0, result.stderr


def test_production_rejects_sms_hmac_reusing_database_password():
    reused = "database-password-that-is-more-than-fifty-characters-long-000000"
    result = import_settings(
        overrides={
            "SMS_VERIFICATION_HMAC_KEY": reused,
            "DATABASE_URL": f"postgresql://app:{reused}@database:5432/xianwen",
        }
    )

    assert result.returncode != 0
    assert "must not reuse DATABASE_URL credentials" in result.stderr


def test_production_rejects_sms_hmac_reusing_redis_password():
    reused = "redis-password-that-is-more-than-fifty-characters-long-00000000"
    result = import_settings(
        overrides={
            "SMS_VERIFICATION_HMAC_KEY": reused,
            "REDIS_URL": f"redis://default:{reused}@redis:6379/0",
        }
    )

    assert result.returncode != 0
    assert "must not reuse REDIS_URL credentials" in result.stderr


def test_production_requires_proxy_networks_when_proxy_hops_enabled():
    result = import_settings(overrides={"TRUSTED_PROXY_HOPS": "1"})

    assert result.returncode != 0
    assert "TRUSTED_PROXY_CIDRS is required" in result.stderr


def test_production_rejects_quota_hmac_reusing_database_password():
    reused = "database-password-that-is-more-than-fifty-characters-long-111111"
    result = import_settings(
        overrides={
            "QUOTA_IDEMPOTENCY_HMAC_KEY": reused,
            "DATABASE_URL": f"postgresql://app:{reused}@database:5432/xianwen",
        }
    )

    assert result.returncode != 0
    assert "QUOTA_IDEMPOTENCY_HMAC_KEY must not reuse DATABASE_URL credentials" in result.stderr


def test_production_rejects_quota_hmac_reusing_redis_password():
    reused = "redis-password-that-is-more-than-fifty-characters-long-11111111"
    result = import_settings(
        overrides={
            "QUOTA_IDEMPOTENCY_HMAC_KEY": reused,
            "REDIS_URL": f"redis://default:{reused}@redis:6379/0",
        }
    )

    assert result.returncode != 0
    assert "QUOTA_IDEMPOTENCY_HMAC_KEY must not reuse REDIS_URL credentials" in result.stderr
