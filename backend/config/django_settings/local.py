# ruff: noqa: F403, F405
import os

from apps.core.logging import build_logging_config

from .base import *

APP_ENV = "local"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "local-test-key-not-for-deployment")
SUBJECT_ENRICHMENT_PROVIDER = "mock"
SUBJECT_ENRICHMENT_MOCK_SCENARIO = "success"
SMS_PROVIDER = os.getenv("SMS_PROVIDER", "mock").strip().lower()
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", "http://localhost:3000")
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:3000")

database_url = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'db.sqlite3'}")
DATABASES = {
    "default": database_from_url(
        database_url,
        conn_max_age=int(os.getenv("DATABASE_CONN_MAX_AGE", "60")),
    )
}

redis_url = os.getenv("REDIS_URL", "").strip()
CACHES = {
    "default": redis_cache(redis_url)
    if redis_url
    else {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "xianwen-local",
    }
}

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "memory://")
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", False)
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", False)
LOGGING = build_logging_config("local")
