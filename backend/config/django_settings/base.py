import os
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
    "apps.users",
    "apps.admin_rbac",
    "apps.plans",
    "apps.quotas",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
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
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_NAME = "xianwen_session"
SESSION_COOKIE_AGE = 12 * 60 * 60
SESSION_COOKIE_PATH = "/"
SESSION_COOKIE_DOMAIN = None
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_SAVE_EVERY_REQUEST = False
CSRF_COOKIE_NAME = "xianwen_csrf"
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_PATH = "/"
CSRF_COOKIE_DOMAIN = None
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
CORS_ALLOW_CREDENTIALS = True
CSRF_FAILURE_VIEW = "apps.core.exceptions.csrf_failure"

AUTH_USER_MODEL = "users.User"
LOGIN_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("LOGIN_RATE_LIMIT_WINDOW_SECONDS", "900"))
LOGIN_RATE_LIMIT_LOCK_SECONDS = int(os.getenv("LOGIN_RATE_LIMIT_LOCK_SECONDS", "900"))
LOGIN_RATE_LIMIT_COMBINATION_FAILURES = int(os.getenv("LOGIN_RATE_LIMIT_COMBINATION_FAILURES", "5"))
LOGIN_RATE_LIMIT_PHONE_FAILURES = int(os.getenv("LOGIN_RATE_LIMIT_PHONE_FAILURES", "10"))
LOGIN_RATE_LIMIT_IP_FAILURES = int(os.getenv("LOGIN_RATE_LIMIT_IP_FAILURES", "30"))
ADMIN_CHALLENGE_TTL_SECONDS = positive_env_int("ADMIN_CHALLENGE_TTL_SECONDS", 300)
ADMIN_REAUTH_LIMIT_FAILURES = positive_env_int("ADMIN_REAUTH_LIMIT_FAILURES", 5)
ADMIN_REAUTH_LIMIT_WINDOW_SECONDS = positive_env_int("ADMIN_REAUTH_LIMIT_WINDOW_SECONDS", 900)
RISK_APPROVAL_TTL_SECONDS = positive_env_int("RISK_APPROVAL_TTL_SECONDS", 86_400)
QUOTA_IDEMPOTENCY_HMAC_KEY = os.getenv(
    "QUOTA_IDEMPOTENCY_HMAC_KEY", "local-test-quota-idempotency-key-not-for-production"
).strip()
if len(QUOTA_IDEMPOTENCY_HMAC_KEY) < 32:
    raise ImproperlyConfigured("QUOTA_IDEMPOTENCY_HMAC_KEY is too weak; minimum length is 32.")
SMS_PROVIDER = os.getenv("SMS_PROVIDER", "unconfigured").strip().lower()
SMS_VERIFICATION_HMAC_KEY = os.getenv(
    "SMS_VERIFICATION_HMAC_KEY", "local-test-sms-hmac-key-not-for-production"
).strip()
if len(SMS_VERIFICATION_HMAC_KEY) < 32:
    raise ImproperlyConfigured("SMS_VERIFICATION_HMAC_KEY is too weak; minimum length is 32.")
SMS_CODE_TTL_SECONDS = positive_env_int("SMS_CODE_TTL_SECONDS", 300)
SMS_RESEND_COOLDOWN_SECONDS = positive_env_int("SMS_RESEND_COOLDOWN_SECONDS", 60)
SMS_MAX_ATTEMPTS = positive_env_int("SMS_MAX_ATTEMPTS", 5)
SMS_LIMIT_COMBINATION_COUNT = positive_env_int("SMS_LIMIT_COMBINATION_COUNT", 5)
SMS_LIMIT_COMBINATION_WINDOW_SECONDS = positive_env_int("SMS_LIMIT_COMBINATION_WINDOW_SECONDS", 900)
SMS_LIMIT_PHONE_COUNT = positive_env_int("SMS_LIMIT_PHONE_COUNT", 10)
SMS_LIMIT_PHONE_WINDOW_SECONDS = positive_env_int("SMS_LIMIT_PHONE_WINDOW_SECONDS", 3600)
SMS_LIMIT_IP_COUNT = positive_env_int("SMS_LIMIT_IP_COUNT", 60)
SMS_LIMIT_IP_WINDOW_SECONDS = positive_env_int("SMS_LIMIT_IP_WINDOW_SECONDS", 3600)
TRUSTED_PROXY_HOPS = int(os.getenv("TRUSTED_PROXY_HOPS", "0"))
if TRUSTED_PROXY_HOPS < 0:
    raise ImproperlyConfigured("TRUSTED_PROXY_HOPS cannot be negative.")
TRUSTED_PROXY_NETWORKS = tuple(
    ip_network(value, strict=False) for value in env_list("TRUSTED_PROXY_CIDRS")
)

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["apps.users.authentication.ApiSessionAuthentication"],
    "DEFAULT_RENDERER_CLASSES": ["apps.core.renderers.ApiJSONRenderer"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "EXCEPTION_HANDLER": "apps.core.exceptions.api_exception_handler",
}

CELERY_TASK_DEFAULT_QUEUE = "system_tasks"
CELERY_TASK_TRACK_STARTED = True
CELERY_TIMEZONE = TIME_ZONE
CELERY_RESULT_BACKEND = None
