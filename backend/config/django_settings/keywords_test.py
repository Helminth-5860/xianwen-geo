# ruff: noqa: F403, F405
import os

from apps.core.logging import build_logging_config

from .base import *

APP_ENV = "local"
DEBUG = False
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
CSRF_TRUSTED_ORIGINS = ["http://testserver"]
CORS_ALLOWED_ORIGINS = ["http://testserver"]
DATABASES = {"default": database_from_url(os.environ["DATABASE_URL"], conn_max_age=0)}
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "xianwen-keywords-test",
    }
}
CELERY_BROKER_URL = "memory://"
SMS_PROVIDER = "mock"
FILE_STORAGE_PROVIDER = "mock"
FILE_SCANNER_PROVIDER = "mock"
DOCUMENT_OCR_PROVIDER = "mock"
SUBJECT_ENRICHMENT_PROVIDER = "mock"
KEYWORD_GENERATION_PROVIDER = "mock"
KEYWORD_GENERATION_MOCK_SCENARIO = "success"
KEYWORD_GENERATION_IDEMPOTENCY_HMAC_KEY = (
    "test-only-keyword-generation-hmac-key-never-use-in-deployment"
)
DISTILLATION_PROVIDER = "mock"
DISTILLATION_MOCK_SCENARIO = "success"
DISTILLATION_IDEMPOTENCY_HMAC_KEY = "test-only-distillation-hmac-key-never-use-in-deployment"
ROOT_URLCONF = "tests.api_urls"
LOGGING = build_logging_config("test")
