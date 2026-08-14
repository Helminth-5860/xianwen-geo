# ruff: noqa: F403, F405
from apps.core.logging import build_logging_config

from .base import *

APP_ENV = "test"
SECRET_KEY = "test-only-key-never-use-in-deployment"
SUBJECT_ENRICHMENT_PROVIDER = "mock"
SUBJECT_ENRICHMENT_MOCK_SCENARIO = "success"
SMS_PROVIDER = "mock"
SMS_VERIFICATION_HMAC_KEY = "test-only-sms-hmac-key-never-use-in-deployment"
QUOTA_IDEMPOTENCY_HMAC_KEY = "test-only-quota-idempotency-key-never-use-in-deployment"
PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY = "test-only-plan-change-idempotency-key-never-use-in-deployment"
FILE_IDEMPOTENCY_HMAC_KEY = "test-only-file-idempotency-key-never-use-in-deployment"
FILE_STORAGE_PROVIDER = "mock"
FILE_SCANNER_PROVIDER = "mock"
DOCUMENT_OCR_PROVIDER = "mock"
SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY = (
    "test-only-subject-enrichment-hmac-key-never-use-in-deployment"
)
WEB_IMPORT_IDEMPOTENCY_HMAC_KEY = "test-only-web-import-idempotency-key-never-use-in-deployment"
WEB_IMPORT_ENABLED = True
WEB_IMPORT_TEST_ALLOWED_CIDRS = (
    ip_network("127.0.0.0/8"),
    ip_network("::1/128"),
)
DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
CSRF_TRUSTED_ORIGINS = ["http://testserver"]
CORS_ALLOWED_ORIGINS = ["http://testserver"]

DATABASES = {
    "default": database_from_url(
        "sqlite:///:memory:",
        conn_max_age=0,
    )
}
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "xianwen-tests",
    }
}

CELERY_BROKER_URL = "memory://"
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
ROOT_URLCONF = "tests.api_urls"
LOGGING = build_logging_config("test")
