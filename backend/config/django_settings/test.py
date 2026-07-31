# ruff: noqa: F403, F405
from apps.core.logging import build_logging_config

from .base import *

APP_ENV = "test"
SECRET_KEY = "test-only-key-never-use-in-deployment"
SMS_PROVIDER = "mock"
SMS_VERIFICATION_HMAC_KEY = "test-only-sms-hmac-key-never-use-in-deployment"
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
