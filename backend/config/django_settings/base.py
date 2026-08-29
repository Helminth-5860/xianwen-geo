import base64
import hashlib
import os
from datetime import timedelta
from ipaddress import ip_network
from pathlib import Path
from urllib.parse import urlsplit

import dj_database_url
from dj_database_url import DBConfig
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parents[2]


def env_bool(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ImproperlyConfigured(f"{name} is required.")
    return value


def positive_env_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value <= 0:
        raise ImproperlyConfigured(f"{name} must be positive.")
    return value


def database_from_url(url: str, *, conn_max_age: int) -> DBConfig:
    return dj_database_url.parse(
        url,
        conn_max_age=conn_max_age,
        conn_health_checks=True,
    )


def redis_cache(url: str) -> dict:
    parsed = urlsplit(url)
    if parsed.scheme not in {"redis", "rediss"}:
        raise ImproperlyConfigured("REDIS_URL must use redis:// or rediss://.")
    return {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": url,
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    }


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "apps.core",
    "apps.ai",
    "apps.geo",
    "apps.users",
    "apps.admin_rbac",
    "apps.plans",
    "apps.quotas",
    "apps.subjects",
    "apps.keywords",
    "apps.questions",
    "apps.documents",
    "apps.web_sources",
    "apps.publication_checks",
    "apps.articles",
    "apps.images",
    "apps.operations",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.core.middleware.SecurityHeadersMiddleware",
    "apps.core.middleware.RequestIdMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.users.middleware.SessionVersionMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "users.User"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "EXCEPTION_HANDLER": "apps.core.exceptions.api_exception_handler",
}

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

PASSWORD_RESET_SESSION_TTL_SECONDS = positive_env_int("PASSWORD_RESET_SESSION_TTL_SECONDS", 600)
AUTH_SMS_CODE_TTL_SECONDS = positive_env_int("AUTH_SMS_CODE_TTL_SECONDS", 300)
AUTH_SMS_RESEND_SECONDS = positive_env_int("AUTH_SMS_RESEND_SECONDS", 60)
AUTH_SMS_MAX_VERIFY_ATTEMPTS = positive_env_int("AUTH_SMS_MAX_VERIFY_ATTEMPTS", 5)
AUTH_SMS_MAX_DAILY_PER_PHONE = positive_env_int("AUTH_SMS_MAX_DAILY_PER_PHONE", 20)
AUTH_SMS_MAX_DAILY_PER_IP = positive_env_int("AUTH_SMS_MAX_DAILY_PER_IP", 100)
AUTH_LOGIN_MAX_FAILURES = positive_env_int("AUTH_LOGIN_MAX_FAILURES", 8)
AUTH_LOGIN_LOCK_SECONDS = positive_env_int("AUTH_LOGIN_LOCK_SECONDS", 900)
AUTH_PASSWORD_MIN_LENGTH = positive_env_int("AUTH_PASSWORD_MIN_LENGTH", 8)
AUTH_PASSWORD_MAX_LENGTH = positive_env_int("AUTH_PASSWORD_MAX_LENGTH", 128)
AUTH_SESSION_COOKIE_AGE_SECONDS = positive_env_int("AUTH_SESSION_COOKIE_AGE_SECONDS", 1209600)
AUTH_ACTIVE_DEVICE_LIMIT = positive_env_int("AUTH_ACTIVE_DEVICE_LIMIT", 10)
AUTH_SESSION_IDLE_TIMEOUT_SECONDS = positive_env_int("AUTH_SESSION_IDLE_TIMEOUT_SECONDS", 86400)
AUTH_SESSION_ROTATE_SECONDS = positive_env_int("AUTH_SESSION_ROTATE_SECONDS", 86400)

SESSION_COOKIE_AGE = AUTH_SESSION_COOKIE_AGE_SECONDS
SESSION_SAVE_EVERY_REQUEST = False
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

SMS_PROVIDER = os.getenv("SMS_PROVIDER", "mock").strip().lower()
SMS_CONSOLE_EXPOSE_CODE = env_bool("SMS_CONSOLE_EXPOSE_CODE", False)
SMS_TENCENT_SECRET_ID = os.getenv("SMS_TENCENT_SECRET_ID", "").strip()
SMS_TENCENT_SECRET_KEY = os.getenv("SMS_TENCENT_SECRET_KEY", "").strip()
SMS_TENCENT_APP_ID = os.getenv("SMS_TENCENT_APP_ID", "").strip()
SMS_TENCENT_SIGN_NAME = os.getenv("SMS_TENCENT_SIGN_NAME", "").strip()
SMS_TENCENT_TEMPLATE_REGISTER = os.getenv("SMS_TENCENT_TEMPLATE_REGISTER", "").strip()
SMS_TENCENT_TEMPLATE_LOGIN = os.getenv("SMS_TENCENT_TEMPLATE_LOGIN", "").strip()
SMS_TENCENT_TEMPLATE_PASSWORD_RESET = os.getenv("SMS_TENCENT_TEMPLATE_PASSWORD_RESET", "").strip()
SMS_TENCENT_REGION = os.getenv("SMS_TENCENT_REGION", "ap-guangzhou").strip()

ADMIN_STEP_UP_TTL_SECONDS = positive_env_int("ADMIN_STEP_UP_TTL_SECONDS", 900)
ADMIN_INITIAL_ROOT_PHONE = os.getenv("ADMIN_INITIAL_ROOT_PHONE", "").strip()
ADMIN_INITIAL_ROOT_PASSWORD = os.getenv("ADMIN_INITIAL_ROOT_PASSWORD", "").strip()
ADMIN_INITIAL_ROOT_NICKNAME = os.getenv("ADMIN_INITIAL_ROOT_NICKNAME", "超级管理员").strip()

WEB_IMPORT_MAX_URL_BYTES = positive_env_int("WEB_IMPORT_MAX_URL_BYTES", 4096)
WEB_IMPORT_MAX_RESPONSE_BYTES = positive_env_int("WEB_IMPORT_MAX_RESPONSE_BYTES", 4 * 1024 * 1024)
WEB_IMPORT_MAX_HEADER_BYTES = positive_env_int("WEB_IMPORT_MAX_HEADER_BYTES", 64 * 1024)
WEB_IMPORT_MAX_HEADER_LINE_BYTES = positive_env_int("WEB_IMPORT_MAX_HEADER_LINE_BYTES", 8 * 1024)
WEB_IMPORT_MAX_HEADER_COUNT = positive_env_int("WEB_IMPORT_MAX_HEADER_COUNT", 128)
WEB_IMPORT_MAX_TEXT_CHARACTERS = positive_env_int("WEB_IMPORT_MAX_TEXT_CHARACTERS", 500_000)
WEB_IMPORT_MAX_REDIRECTS = positive_env_int("WEB_IMPORT_MAX_REDIRECTS", 5)
WEB_IMPORT_CONNECT_TIMEOUT_SECONDS = positive_env_int("WEB_IMPORT_CONNECT_TIMEOUT_SECONDS", 4)
WEB_IMPORT_READ_TIMEOUT_SECONDS = positive_env_int("WEB_IMPORT_READ_TIMEOUT_SECONDS", 6)
WEB_IMPORT_TOTAL_TIMEOUT_SECONDS = positive_env_int("WEB_IMPORT_TOTAL_TIMEOUT_SECONDS", 12)
WEB_IMPORT_USER_AGENT = os.getenv("WEB_IMPORT_USER_AGENT", "XianwenGeoBot/1.0").strip()
WEB_IMPORT_IDEMPOTENCY_HMAC_KEY = os.getenv(
    "WEB_IMPORT_IDEMPOTENCY_HMAC_KEY",
    "local-test-only-web-import-idempotency-hmac-key",
).strip()
WEB_IMPORT_TEST_ALLOWED_CIDRS = tuple(
    ip_network(item, strict=False) for item in env_list("WEB_IMPORT_TEST_ALLOWED_CIDRS")
)

ARTICLE_COMPARISON_TTL_SECONDS = positive_env_int("ARTICLE_COMPARISON_TTL_SECONDS", 900)
ARTICLE_SOURCE_PACK_MAX_ITEMS = positive_env_int("ARTICLE_SOURCE_PACK_MAX_ITEMS", 100)
ARTICLE_EXPORT_MAX_BYTES = positive_env_int("ARTICLE_EXPORT_MAX_BYTES", 4 * 1024 * 1024)

AI_KEY_ENCRYPTION_KEY = os.getenv("AI_KEY_ENCRYPTION_KEY", "").strip()
if not AI_KEY_ENCRYPTION_KEY:
    AI_KEY_ENCRYPTION_KEY = base64.urlsafe_b64encode(hashlib.sha256(b"local-ai-key").digest()).decode()
