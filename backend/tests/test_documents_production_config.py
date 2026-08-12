from tests.test_production_settings import import_settings


def test_production_rejects_file_hmac_reusing_database_password():
    reused = "database-password-that-is-more-than-fifty-characters-long-file"
    result = import_settings(
        overrides={
            "FILE_IDEMPOTENCY_HMAC_KEY": reused,
            "DATABASE_URL": f"postgresql://app:{reused}@database:5432/xianwen",
        }
    )
    assert result.returncode != 0
    assert "FILE_IDEMPOTENCY_HMAC_KEY must not reuse DATABASE_URL credentials" in result.stderr


def test_production_rejects_file_hmac_reusing_redis_password():
    reused = "redis-password-that-is-more-than-fifty-characters-long-file"
    result = import_settings(
        overrides={
            "FILE_IDEMPOTENCY_HMAC_KEY": reused,
            "REDIS_URL": f"redis://default:{reused}@redis:6379/0",
        }
    )
    assert result.returncode != 0
    assert "FILE_IDEMPOTENCY_HMAC_KEY must not reuse REDIS_URL credentials" in result.stderr


def test_production_rejects_file_hmac_reusing_storage_secret():
    reused = "storage-secret-that-is-more-than-fifty-characters-long-file"
    result = import_settings(
        overrides={
            "FILE_STORAGE_PROVIDER": "s3",
            "FILE_IDEMPOTENCY_HMAC_KEY": reused,
            "S3_ENDPOINT_URL": "https://storage.example.com",
            "S3_REGION": "test-region-1",
            "S3_BUCKET": "private-files",
            "S3_ACCESS_KEY": "placeholder-access-key",
            "S3_SECRET_KEY": reused,
        }
    )
    assert result.returncode != 0
    assert "FILE_IDEMPOTENCY_HMAC_KEY must not reuse S3_SECRET_KEY" in result.stderr


def test_production_rejects_wildcard_file_application_origin():
    result = import_settings(overrides={"FILE_ALLOWED_APP_ORIGINS": "*"})
    assert result.returncode != 0
    assert "Wildcard file application origins are forbidden" in result.stderr


def test_production_rejects_non_http_file_application_origin():
    result = import_settings(overrides={"FILE_ALLOWED_APP_ORIGINS": "file:///tmp/app"})
    assert result.returncode != 0
    assert "FILE_ALLOWED_APP_ORIGINS must contain HTTP(S) origins" in result.stderr


def test_production_rejects_unknown_file_providers():
    storage = import_settings(overrides={"FILE_STORAGE_PROVIDER": "mystery"})
    scanner = import_settings(overrides={"FILE_SCANNER_PROVIDER": "mystery"})
    assert storage.returncode != 0
    assert "Unsupported production file storage provider" in storage.stderr
    assert scanner.returncode != 0
    assert "Unsupported production file scanner provider" in scanner.stderr
