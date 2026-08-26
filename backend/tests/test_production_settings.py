import base64
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
FERNET_TEST_KEY = base64.urlsafe_b64encode(
    hashlib.sha256(b"xianwen-production-settings-fernet-test-key").digest()
).decode("ascii")
REQUIRED_ENVIRONMENT = {
    "APP_ENV": "production",
    "DJANGO_SETTINGS_MODULE": "config.settings",
    "DJANGO_SECRET_KEY": "x" * 64,
    "DJANGO_DEBUG": "false",
    "SMS_VERIFICATION_HMAC_KEY": "s" * 64,
    "QUOTA_IDEMPOTENCY_HMAC_KEY": "q" * 64,
    "GEO_DETECTION_IDEMPOTENCY_HMAC_KEY": "g" * 64,
    "PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY": "p" * 64,
    "FILE_IDEMPOTENCY_HMAC_KEY": "f" * 64,
    "IMAGE_IDEMPOTENCY_HMAC_KEY": "i" * 64,
    "WEB_IMPORT_IDEMPOTENCY_HMAC_KEY": "w" * 64,
    "SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY": "e" * 64,
    "KEYWORD_GENERATION_IDEMPOTENCY_HMAC_KEY": "k" * 64,
    "DISTILLATION_IDEMPOTENCY_HMAC_KEY": "d" * 64,
    "QUESTION_GENERATION_IDEMPOTENCY_HMAC_KEY": "u" * 64,
    "ARTICLE_IDEMPOTENCY_HMAC_KEY": "a" * 64,
    "REPORT_SHARE_HMAC_KEY": "r" * 64,
    "FIELD_ENCRYPTION_MASTER_KEY": FERNET_TEST_KEY,
    "API_CREDENTIAL_ENVIRONMENT": "production",
    "SMS_PROVIDER": "unconfigured",
    "FILE_STORAGE_PROVIDER": "unavailable",
    "FILE_SCANNER_PROVIDER": "unavailable",
    "DOCUMENT_OCR_PROVIDER": "unavailable",
    "FILE_ALLOWED_APP_ORIGINS": "https://app.example.com",
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
            "GEO_DETECTION_IDEMPOTENCY_HMAC_KEY",
            "PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY",
            "FILE_IDEMPOTENCY_HMAC_KEY",
            "IMAGE_IDEMPOTENCY_HMAC_KEY",
            "WEB_IMPORT_IDEMPOTENCY_HMAC_KEY",
            "SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY",
            "SUBJECT_ENRICHMENT_PROVIDER",
            "KEYWORD_GENERATION_IDEMPOTENCY_HMAC_KEY",
            "KEYWORD_GENERATION_PROVIDER",
            "DISTILLATION_IDEMPOTENCY_HMAC_KEY",
            "DISTILLATION_PROVIDER",
            "QUESTION_GENERATION_IDEMPOTENCY_HMAC_KEY",
            "QUESTION_GENERATION_PROVIDER",
            "ARTICLE_IDEMPOTENCY_HMAC_KEY",
            "REPORT_SHARE_HMAC_KEY",
            "FIELD_ENCRYPTION_MASTER_KEY",
            "API_CREDENTIAL_ENVIRONMENT",
            "SMS_PROVIDER",
            "FILE_STORAGE_PROVIDER",
            "FILE_SCANNER_PROVIDER",
            "DOCUMENT_OCR_PROVIDER",
            "FILE_ALLOWED_APP_ORIGINS",
            "DATABASE_URL",
            "REDIS_URL",
            "ALLOWED_HOSTS",
            "CSRF_TRUSTED_ORIGINS",
            "CORS_ALLOWED_ORIGINS",
            "RELEASE_ENFORCE_EXTERNAL_READINESS",
            "RELEASE_DEPLOY_SHA",
            "CLAMAV_HOST",
            "S3_ENDPOINT_URL",
            "S3_REGION",
            "S3_BUCKET",
            "S3_ACCESS_KEY",
            "S3_SECRET_KEY",
            "ENABLE_REAL_SMS",
            "SMS_REGION",
            "SMS_APP_ID",
            "SMS_SECRET_ID",
            "SMS_SECRET_KEY",
            "SMS_SIGN_NAME",
            "SMS_TEMPLATE_REGISTER",
            "SMS_TEMPLATE_LOGIN",
            "SMS_TEMPLATE_SECURITY",
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
        "GEO_DETECTION_IDEMPOTENCY_HMAC_KEY",
        "PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY",
        "FILE_IDEMPOTENCY_HMAC_KEY",
        "IMAGE_IDEMPOTENCY_HMAC_KEY",
        "WEB_IMPORT_IDEMPOTENCY_HMAC_KEY",
        "SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY",
        "KEYWORD_GENERATION_IDEMPOTENCY_HMAC_KEY",
        "DISTILLATION_IDEMPOTENCY_HMAC_KEY",
        "ARTICLE_IDEMPOTENCY_HMAC_KEY",
        "REPORT_SHARE_HMAC_KEY",
        "FIELD_ENCRYPTION_MASTER_KEY",
        "API_CREDENTIAL_ENVIRONMENT",
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
        ({"FIELD_ENCRYPTION_MASTER_KEY": "invalid"}, "must be a valid Fernet key"),
        (
            {
                "FIELD_ENCRYPTION_MASTER_KEY": base64.urlsafe_b64encode(
                    hashlib.sha256(
                        b"xianwen-local-field-encryption-key-not-for-production"
                    ).digest()
                ).decode("ascii")
            },
            "must not use the local default",
        ),
        ({"API_CREDENTIAL_ENVIRONMENT": "local"}, "must be staging or production"),
        (
            {"SMS_VERIFICATION_HMAC_KEY": "weak"},
            "SMS_VERIFICATION_HMAC_KEY is too weak",
        ),
        (
            {"QUOTA_IDEMPOTENCY_HMAC_KEY": "weak"},
            "QUOTA_IDEMPOTENCY_HMAC_KEY is too weak",
        ),
        (
            {"GEO_DETECTION_IDEMPOTENCY_HMAC_KEY": "weak"},
            "GEO_DETECTION_IDEMPOTENCY_HMAC_KEY is too weak",
        ),
        (
            {"GEO_DETECTION_IDEMPOTENCY_HMAC_KEY": "q" * 64},
            "GEO_DETECTION_IDEMPOTENCY_HMAC_KEY must not reuse another application secret",
        ),
        (
            {"IMAGE_IDEMPOTENCY_HMAC_KEY": "weak"},
            "IMAGE_IDEMPOTENCY_HMAC_KEY is too weak",
        ),
        (
            {"IMAGE_IDEMPOTENCY_HMAC_KEY": "f" * 64},
            "IMAGE_IDEMPOTENCY_HMAC_KEY must not reuse another secret",
        ),
        (
            {"WEB_IMPORT_IDEMPOTENCY_HMAC_KEY": "i" * 64},
            "WEB_IMPORT_IDEMPOTENCY_HMAC_KEY must not reuse another secret",
        ),
        (
            {"PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY": "weak"},
            "PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY is too weak",
        ),
        (
            {"FILE_IDEMPOTENCY_HMAC_KEY": "weak"},
            "FILE_IDEMPOTENCY_HMAC_KEY is too weak",
        ),
        (
            {"WEB_IMPORT_IDEMPOTENCY_HMAC_KEY": "weak"},
            "WEB_IMPORT_IDEMPOTENCY_HMAC_KEY is too weak",
        ),
        (
            {"PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY": "x" * 64},
            "must not reuse another application secret",
        ),
        ({"SMS_PROVIDER": "mock"}, "Mock SMS provider is forbidden"),
        ({"FILE_STORAGE_PROVIDER": "mock"}, "Mock file storage provider is forbidden"),
        ({"FILE_SCANNER_PROVIDER": "mock"}, "Mock file scanner is forbidden"),
        (
            {"DOCUMENT_OCR_PROVIDER": "mock"},
            "Mock or unknown OCR providers are forbidden",
        ),
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
        (
            {"FILE_IDEMPOTENCY_HMAC_KEY": "x" * 64},
            "must not reuse another secret",
        ),
        (
            {"FILE_IDEMPOTENCY_HMAC_KEY": "q" * 64},
            "must not reuse another secret",
        ),
        (
            {"WEB_IMPORT_IDEMPOTENCY_HMAC_KEY": "x" * 64},
            "must not reuse another secret",
        ),
        (
            {"SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY": "weak"},
            "SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY is too weak",
        ),
        (
            {"SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY": "x" * 64},
            "SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY must be independent",
        ),
        (
            {"SUBJECT_ENRICHMENT_PROVIDER": "mock"},
            "Mock subject enrichment provider is forbidden",
        ),
        (
            {"SUBJECT_ENRICHMENT_PROVIDER": "deepseek"},
            "Only unavailable subject enrichment provider is supported",
        ),
        (
            {"KEYWORD_GENERATION_IDEMPOTENCY_HMAC_KEY": "weak"},
            "KEYWORD_GENERATION_IDEMPOTENCY_HMAC_KEY is too weak",
        ),
        (
            {"KEYWORD_GENERATION_IDEMPOTENCY_HMAC_KEY": "x" * 64},
            "KEYWORD_GENERATION_IDEMPOTENCY_HMAC_KEY must be independent",
        ),
        (
            {"KEYWORD_GENERATION_PROVIDER": "mock"},
            "Mock keyword generation provider is forbidden",
        ),
        (
            {"KEYWORD_GENERATION_PROVIDER": "unsupported"},
            "Only unavailable or deepseek keyword generation provider is supported",
        ),
        (
            {"DISTILLATION_IDEMPOTENCY_HMAC_KEY": "weak"},
            "DISTILLATION_IDEMPOTENCY_HMAC_KEY is too weak",
        ),
        (
            {"DISTILLATION_IDEMPOTENCY_HMAC_KEY": "x" * 64},
            "DISTILLATION_IDEMPOTENCY_HMAC_KEY must be independent",
        ),
        (
            {"DISTILLATION_PROVIDER": "mock"},
            "Mock distillation provider is forbidden",
        ),
        (
            {"DISTILLATION_PROVIDER": "unsupported"},
            "Only unavailable or deepseek distillation provider is supported",
        ),
        (
            {"QUESTION_GENERATION_IDEMPOTENCY_HMAC_KEY": "weak"},
            "QUESTION_GENERATION_IDEMPOTENCY_HMAC_KEY is too weak",
        ),
        (
            {"QUESTION_GENERATION_IDEMPOTENCY_HMAC_KEY": "x" * 64},
            "QUESTION_GENERATION_IDEMPOTENCY_HMAC_KEY must be independent",
        ),
        (
            {"QUESTION_GENERATION_PROVIDER": "mock"},
            "Mock question generation provider is forbidden",
        ),
        (
            {"QUESTION_GENERATION_PROVIDER": "unsupported"},
            "Only unavailable or deepseek question generation provider is supported",
        ),
        (
            {"ARTICLE_IDEMPOTENCY_HMAC_KEY": "weak"},
            "ARTICLE_IDEMPOTENCY_HMAC_KEY is too weak",
        ),
        (
            {"REPORT_SHARE_HMAC_KEY": "weak"},
            "REPORT_SHARE_HMAC_KEY is too weak",
        ),
        (
            {"REPORT_SHARE_HMAC_KEY": "a" * 64},
            "Stage 2 HMAC keys must be independent",
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


def test_production_accepts_deepseek_keyword_generation_provider():
    result = import_settings(overrides={"KEYWORD_GENERATION_PROVIDER": "deepseek"})
    assert result.returncode == 0, result.stderr


def test_production_accepts_deepseek_distillation_provider():
    result = import_settings(overrides={"DISTILLATION_PROVIDER": "deepseek"})
    assert result.returncode == 0, result.stderr


def test_production_accepts_deepseek_question_generation_provider():
    result = import_settings(overrides={"QUESTION_GENERATION_PROVIDER": "deepseek"})
    assert result.returncode == 0, result.stderr


def test_production_release_enforcement_requires_exact_sha_and_external_dependencies():
    invalid_sha = import_settings(
        overrides={"RELEASE_ENFORCE_EXTERNAL_READINESS": "true", "RELEASE_DEPLOY_SHA": "abc"}
    )
    assert invalid_sha.returncode != 0
    assert "RELEASE_DEPLOY_SHA must be a full lowercase Git SHA" in invalid_sha.stderr

    missing_dependencies = import_settings(
        overrides={
            "RELEASE_ENFORCE_EXTERNAL_READINESS": "true",
            "RELEASE_DEPLOY_SHA": "1" * 40,
        }
    )
    assert missing_dependencies.returncode != 0
    assert "External readiness requires private S3 storage and ClamAV scanning" in (
        missing_dependencies.stderr
    )


def test_production_clamav_requires_an_explicit_host():
    result = import_settings(overrides={"FILE_SCANNER_PROVIDER": "clamav"})
    assert result.returncode != 0
    assert "CLAMAV_HOST is required" in result.stderr


def test_production_rejects_storage_secret_reuse_across_release_credentials():
    result = import_settings(
        overrides={
            "FILE_STORAGE_PROVIDER": "s3",
            "S3_ENDPOINT_URL": "https://cos.example.com",
            "S3_REGION": "ap-shanghai",
            "S3_BUCKET": "xianwen-private",
            "S3_ACCESS_KEY": "storage-access-id",
            "S3_SECRET_KEY": "x" * 64,
        }
    )
    assert result.returncode != 0
    assert "S3_SECRET_KEY must not reuse the value configured for DJANGO_SECRET_KEY" in (
        result.stderr
    )


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


def test_production_rejects_subject_enrichment_hmac_reusing_database_password():
    reused = "database-password-that-is-more-than-fifty-characters-long-333333"
    result = import_settings(
        overrides={
            "SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY": reused,
            "DATABASE_URL": f"postgresql://app:{reused}@database:5432/xianwen",
        }
    )

    assert result.returncode != 0
    assert (
        "SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY must not reuse DATABASE_URL credentials"
        in result.stderr
    )


def test_production_rejects_subject_enrichment_hmac_reusing_redis_password():
    reused = "redis-password-that-is-more-than-fifty-characters-long-33333333"
    result = import_settings(
        overrides={
            "SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY": reused,
            "REDIS_URL": f"redis://default:{reused}@redis:6379/0",
        }
    )

    assert result.returncode != 0
    assert (
        "SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY must not reuse REDIS_URL credentials"
        in result.stderr
    )


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


def test_production_rejects_image_hmac_reusing_database_password():
    reused = "database-password-that-is-more-than-fifty-characters-long-image"
    result = import_settings(
        overrides={
            "IMAGE_IDEMPOTENCY_HMAC_KEY": reused,
            "DATABASE_URL": f"postgresql://app:{reused}@database:5432/xianwen",
        }
    )

    assert result.returncode != 0
    assert "IMAGE_IDEMPOTENCY_HMAC_KEY must not reuse DATABASE_URL credentials" in result.stderr


def test_production_rejects_image_hmac_reusing_redis_password():
    reused = "redis-password-that-is-more-than-fifty-characters-long-image"
    result = import_settings(
        overrides={
            "IMAGE_IDEMPOTENCY_HMAC_KEY": reused,
            "REDIS_URL": f"redis://default:{reused}@redis:6379/0",
        }
    )

    assert result.returncode != 0
    assert "IMAGE_IDEMPOTENCY_HMAC_KEY must not reuse REDIS_URL credentials" in result.stderr


def test_production_rejects_plan_change_hmac_reusing_database_password():
    reused = "database-password-that-is-more-than-fifty-characters-long-222222"
    result = import_settings(
        overrides={
            "PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY": reused,
            "DATABASE_URL": f"postgresql://app:{reused}@database:5432/xianwen",
        }
    )
    assert result.returncode != 0
    assert (
        "PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY must not reuse DATABASE_URL credentials" in result.stderr
    )


def test_production_rejects_plan_change_hmac_reusing_redis_password():
    reused = "redis-password-that-is-more-than-fifty-characters-long-22222222"
    result = import_settings(
        overrides={
            "PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY": reused,
            "REDIS_URL": f"redis://default:{reused}@redis:6379/0",
        }
    )
    assert result.returncode != 0
    assert "PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY must not reuse REDIS_URL credentials" in result.stderr


def test_production_rejects_field_encryption_key_reusing_database_password():
    key = FERNET_TEST_KEY
    result = import_settings(
        overrides={
            "FIELD_ENCRYPTION_MASTER_KEY": key,
            "DATABASE_URL": f"postgresql://app:{key}@database:5432/xianwen",
        }
    )
    assert result.returncode != 0
    assert "FIELD_ENCRYPTION_MASTER_KEY must not reuse DATABASE_URL credentials" in result.stderr


def test_production_rejects_field_encryption_key_reusing_redis_password():
    key = FERNET_TEST_KEY
    result = import_settings(
        overrides={
            "FIELD_ENCRYPTION_MASTER_KEY": key,
            "REDIS_URL": f"redis://:{key}@redis:6379/0",
        }
    )
    assert result.returncode != 0
    assert "FIELD_ENCRYPTION_MASTER_KEY must not reuse REDIS_URL credentials" in result.stderr
