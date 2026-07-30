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
    ],
)
def test_production_rejects_unsafe_configuration(overrides, expected_error):
    result = import_settings(overrides=overrides)
    assert result.returncode != 0
    assert expected_error in result.stderr


def test_production_accepts_complete_safe_configuration():
    result = import_settings()
    assert result.returncode == 0, result.stderr
