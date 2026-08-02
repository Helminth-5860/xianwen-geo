# ruff: noqa: F403, F405
import os
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

from apps.core.logging import build_logging_config

from .base import *

APP_ENV = "production"

SECRET_KEY = require_env("DJANGO_SECRET_KEY")
SMS_VERIFICATION_HMAC_KEY = require_env("SMS_VERIFICATION_HMAC_KEY")
QUOTA_IDEMPOTENCY_HMAC_KEY = require_env("QUOTA_IDEMPOTENCY_HMAC_KEY")
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
if len(SMS_VERIFICATION_HMAC_KEY) < 50 or SMS_VERIFICATION_HMAC_KEY.lower() in weak_secret_markers:
    raise ImproperlyConfigured("SMS_VERIFICATION_HMAC_KEY is too weak for production.")
if SMS_VERIFICATION_HMAC_KEY == SECRET_KEY:
    raise ImproperlyConfigured("SMS_VERIFICATION_HMAC_KEY must not reuse DJANGO_SECRET_KEY.")
if (
    len(QUOTA_IDEMPOTENCY_HMAC_KEY) < 50
    or QUOTA_IDEMPOTENCY_HMAC_KEY.lower() in weak_secret_markers
):
    raise ImproperlyConfigured("QUOTA_IDEMPOTENCY_HMAC_KEY is too weak for production.")
if QUOTA_IDEMPOTENCY_HMAC_KEY in {SECRET_KEY, SMS_VERIFICATION_HMAC_KEY}:
    raise ImproperlyConfigured(
        "QUOTA_IDEMPOTENCY_HMAC_KEY must not reuse another application secret."
    )
for forbidden_variable in ("DATABASE_URL", "REDIS_URL"):
    configured_url = os.getenv(forbidden_variable, "")
    configured_password = urlsplit(configured_url).password if configured_url else None
    if SMS_VERIFICATION_HMAC_KEY in {configured_url, configured_password}:
        raise ImproperlyConfigured(
            f"SMS_VERIFICATION_HMAC_KEY must not reuse {forbidden_variable} credentials."
        )

    if QUOTA_IDEMPOTENCY_HMAC_KEY in {configured_url, configured_password}:
        raise ImproperlyConfigured(
            f"QUOTA_IDEMPOTENCY_HMAC_KEY must not reuse {forbidden_variable} credentials."
        )
SMS_PROVIDER = os.getenv("SMS_PROVIDER", "unconfigured").strip().lower()
if SMS_PROVIDER == "mock":
    raise ImproperlyConfigured("Mock SMS provider is forbidden in production.")
if TRUSTED_PROXY_HOPS > 0 and not TRUSTED_PROXY_NETWORKS:
    raise ImproperlyConfigured(
        "TRUSTED_PROXY_CIDRS is required when TRUSTED_PROXY_HOPS is enabled."
    )

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
