# ruff: noqa: F403, F405
import os
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

from apps.core.logging import build_logging_config

from .base import *

APP_ENV = "production"

SECRET_KEY = require_env("DJANGO_SECRET_KEY")
weak_secret_markers = {
    "changeme",
    "change-me",
    "default",
    "local-development-only-change-before-deployment",
    "local-test-key-not-for-deployment",
    "replace-via-secret-manager",
}
if len(SECRET_KEY) < 50 or SECRET_KEY.lower() in weak_secret_markers:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY is too weak for production.")

DEBUG = env_bool("DJANGO_DEBUG", False)
if DEBUG:
    raise ImproperlyConfigured("DJANGO_DEBUG must be false in production.")

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS")
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("ALLOWED_HOSTS is required.")
if "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("Wildcard ALLOWED_HOSTS is forbidden in production.")

CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
if not CSRF_TRUSTED_ORIGINS:
    raise ImproperlyConfigured("CSRF_TRUSTED_ORIGINS is required.")

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS")
if not CORS_ALLOWED_ORIGINS:
    raise ImproperlyConfigured("CORS_ALLOWED_ORIGINS is required.")

for variable_name, origins in {
    "CSRF_TRUSTED_ORIGINS": CSRF_TRUSTED_ORIGINS,
    "CORS_ALLOWED_ORIGINS": CORS_ALLOWED_ORIGINS,
}.items():
    if any(urlsplit(origin).scheme not in {"http", "https"} for origin in origins):
        raise ImproperlyConfigured(f"{variable_name} must contain HTTP(S) origins.")

database_url = require_env("DATABASE_URL")
database_config = database_from_url(
    database_url,
    conn_max_age=int(os.getenv("DATABASE_CONN_MAX_AGE", "60")),
)
if database_config["ENGINE"] == "django.db.backends.sqlite3":
    raise ImproperlyConfigured("SQLite is forbidden in production.")
DATABASES = {"default": database_config}

redis_url = require_env("REDIS_URL")
CACHES = {"default": redis_cache(redis_url)}

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", redis_url)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
LOGGING = build_logging_config("production")
