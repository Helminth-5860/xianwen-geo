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
    "apps.website_audits",
    "apps.source_index",
    "apps.publishing",
    "apps.articles",
    "apps.images",
    "apps.videos",
    "apps.media_inquiries",
    "apps.websites",
    "apps.operations",
]

PAID_MEDIA_CATALOG_PATH = os.getenv(
    "PAID_MEDIA_CATALOG_PATH",
    str(BASE_DIR.parent / "config" / "paid-media-catalog.json"),
).strip()

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
REGISTRATION_REF_MAX_AGE_SECONDS = positive_env_int(
    "REGISTRATION_REF_MAX_AGE_SECONDS", 30 * 24 * 60 * 60
)
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
GEO_DETECTION_IDEMPOTENCY_HMAC_KEY = os.getenv(
    "GEO_DETECTION_IDEMPOTENCY_HMAC_KEY",
    "local-test-geo-detection-idempotency-key-not-for-production",
).strip()
if len(GEO_DETECTION_IDEMPOTENCY_HMAC_KEY) < 32:
    raise ImproperlyConfigured(
        "GEO_DETECTION_IDEMPOTENCY_HMAC_KEY is too weak; minimum length is 32."
    )
GEO_DETECTION_GLOBAL_MAX_CONCURRENCY = positive_env_int("GEO_DETECTION_GLOBAL_MAX_CONCURRENCY", 32)
GEO_DETECTION_QUEUE_TIMEOUT_SECONDS = positive_env_int("GEO_DETECTION_QUEUE_TIMEOUT_SECONDS", 900)
GEO_DETECTION_DISPATCH_BATCH = positive_env_int("GEO_DETECTION_DISPATCH_BATCH", 100)
GEO_DETECTION_INTERNAL_MAX_RETRIES = positive_env_int("GEO_DETECTION_INTERNAL_MAX_RETRIES", 3)
SMS_PROVIDER = os.getenv("SMS_PROVIDER", "unconfigured").strip().lower()
ENABLE_REAL_SMS = env_bool("ENABLE_REAL_SMS", False)
SMS_REGION = os.getenv("SMS_REGION", "").strip()
SMS_APP_ID = os.getenv("SMS_APP_ID", "").strip()
SMS_SECRET_ID = os.getenv("SMS_SECRET_ID", "").strip()
SMS_SECRET_KEY = os.getenv("SMS_SECRET_KEY", "").strip()
SMS_SIGN_NAME = os.getenv("SMS_SIGN_NAME", "").strip()
SMS_TEMPLATE_REGISTER = os.getenv("SMS_TEMPLATE_REGISTER", "").strip()
SMS_TEMPLATE_LOGIN = os.getenv("SMS_TEMPLATE_LOGIN", "").strip()
SMS_TEMPLATE_SECURITY = os.getenv("SMS_TEMPLATE_SECURITY", "").strip()
SMS_TEMPLATE_REVIEW = os.getenv("SMS_TEMPLATE_REVIEW", "").strip()
SMS_TEMPLATE_PLAN_EXPIRY = os.getenv("SMS_TEMPLATE_PLAN_EXPIRY", "").strip()
SMS_PROVIDER_TIMEOUT_SECONDS = positive_env_int("SMS_PROVIDER_TIMEOUT_SECONDS", 10)
if SMS_PROVIDER_TIMEOUT_SECONDS > 60:
    raise ImproperlyConfigured("SMS_PROVIDER_TIMEOUT_SECONDS must not exceed 60.")
PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY = os.getenv(
    "PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY",
    "local-test-plan-change-idempotency-key-not-for-production",
).strip()
if len(PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY) < 32:
    raise ImproperlyConfigured(
        "PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY is too weak; minimum length is 32."
    )
FILE_IDEMPOTENCY_HMAC_KEY = os.getenv(
    "FILE_IDEMPOTENCY_HMAC_KEY",
    "local-test-file-idempotency-key-not-for-production",
).strip()
if len(FILE_IDEMPOTENCY_HMAC_KEY) < 32:
    raise ImproperlyConfigured("FILE_IDEMPOTENCY_HMAC_KEY is too weak; minimum length is 32.")
FILE_STORAGE_PROVIDER = os.getenv("FILE_STORAGE_PROVIDER", "s3").strip().lower()
FILE_SCANNER_PROVIDER = os.getenv("FILE_SCANNER_PROVIDER", "mock").strip().lower()
CLAMAV_HOST = os.getenv("CLAMAV_HOST", "").strip()
CLAMAV_PORT = positive_env_int("CLAMAV_PORT", 3310)
CLAMAV_TIMEOUT_SECONDS = positive_env_int("CLAMAV_TIMEOUT_SECONDS", 10)
if CLAMAV_TIMEOUT_SECONDS > 60:
    raise ImproperlyConfigured("CLAMAV_TIMEOUT_SECONDS must not exceed 60.")
FILE_UPLOAD_MAX_BYTES = positive_env_int("FILE_UPLOAD_MAX_BYTES", 50 * 1024 * 1024)
FILE_UPLOAD_URL_TTL = positive_env_int("FILE_UPLOAD_URL_TTL", 300)
FILE_DOWNLOAD_URL_TTL = positive_env_int("FILE_DOWNLOAD_URL_TTL", 300)
FILE_STAGING_RETENTION_SECONDS = positive_env_int("FILE_STAGING_RETENTION_SECONDS", 3600)
FILE_VALIDATION_MAX_ARCHIVE_ENTRIES = positive_env_int("FILE_VALIDATION_MAX_ARCHIVE_ENTRIES", 2000)
FILE_VALIDATION_MAX_UNCOMPRESSED_BYTES = positive_env_int(
    "FILE_VALIDATION_MAX_UNCOMPRESSED_BYTES", 200 * 1024 * 1024
)
FILE_VALIDATION_MAX_ARCHIVE_ENTRY_BYTES = positive_env_int(
    "FILE_VALIDATION_MAX_ARCHIVE_ENTRY_BYTES", 50 * 1024 * 1024
)
IMAGE_IDEMPOTENCY_HMAC_KEY = os.getenv(
    "IMAGE_IDEMPOTENCY_HMAC_KEY",
    "local-test-image-idempotency-key-not-for-production",
).strip()
if len(IMAGE_IDEMPOTENCY_HMAC_KEY) < 32:
    raise ImproperlyConfigured("IMAGE_IDEMPOTENCY_HMAC_KEY is too weak; minimum length is 32.")
IMAGE_PROMPT_MAX_LENGTH = positive_env_int("IMAGE_PROMPT_MAX_LENGTH", 4000)
IMAGE_MAX_BYTES = positive_env_int("IMAGE_MAX_BYTES", 10 * 1024 * 1024)
IMAGE_MAX_PIXELS = positive_env_int("IMAGE_MAX_PIXELS", 40_000_000)
IMAGE_BATCH_RETENTION_SECONDS = positive_env_int("IMAGE_BATCH_RETENTION_SECONDS", 86_400)
VIDEO_PROVIDER = os.getenv("VIDEO_PROVIDER", "unavailable").strip().lower()
if VIDEO_PROVIDER not in {"unavailable", "aliyun"}:
    raise ImproperlyConfigured("VIDEO_PROVIDER must be unavailable or aliyun.")
VIDEO_MODEL = os.getenv("VIDEO_MODEL", "wan2.6-i2v-flash").strip()
VIDEO_RESOLUTION = os.getenv("VIDEO_RESOLUTION", "720P").strip().upper()
if VIDEO_MODEL != "wan2.6-i2v-flash":
    raise ImproperlyConfigured("VIDEO_MODEL must be wan2.6-i2v-flash.")
if VIDEO_RESOLUTION != "720P":
    raise ImproperlyConfigured("VIDEO_RESOLUTION must be 720P.")
VIDEO_ALLOWED_DURATIONS = (5, 10)
VIDEO_ALLOWED_ASPECT_RATIOS = ("9:16", "16:9")
VIDEO_PROMPT_MAX_LENGTH = positive_env_int("VIDEO_PROMPT_MAX_LENGTH", 1500)
if VIDEO_PROMPT_MAX_LENGTH > 1500:
    raise ImproperlyConfigured("VIDEO_PROMPT_MAX_LENGTH must not exceed 1500.")
VIDEO_SOURCE_IMAGE_MAX_BYTES = positive_env_int("VIDEO_SOURCE_IMAGE_MAX_BYTES", 20 * 1024 * 1024)
VIDEO_MAX_BYTES = positive_env_int("VIDEO_MAX_BYTES", 128 * 1024 * 1024)
if VIDEO_MAX_BYTES > 128 * 1024 * 1024:
    raise ImproperlyConfigured("VIDEO_MAX_BYTES must not exceed 128 MiB.")
VIDEO_POLL_SECONDS = positive_env_int("VIDEO_POLL_SECONDS", 15)
VIDEO_MAX_POLLS = positive_env_int("VIDEO_MAX_POLLS", 240)
VIDEO_PROVIDER_TIMEOUT_SECONDS = positive_env_int("VIDEO_PROVIDER_TIMEOUT_SECONDS", 30)
VIDEO_DOWNLOAD_TIMEOUT_SECONDS = positive_env_int("VIDEO_DOWNLOAD_TIMEOUT_SECONDS", 180)
VIDEO_JOB_LEASE_SECONDS = positive_env_int("VIDEO_JOB_LEASE_SECONDS", 390)
if VIDEO_JOB_LEASE_SECONDS <= 330:
    raise ImproperlyConfigured("VIDEO_JOB_LEASE_SECONDS must exceed the video task hard limit.")
VIDEO_IDEMPOTENCY_HMAC_KEY = os.getenv(
    "VIDEO_IDEMPOTENCY_HMAC_KEY",
    "local-test-video-idempotency-key-not-for-production",
).strip()
if len(VIDEO_IDEMPOTENCY_HMAC_KEY) < 32:
    raise ImproperlyConfigured("VIDEO_IDEMPOTENCY_HMAC_KEY is too weak; minimum length is 32.")
ALIYUN_VIDEO_API_BASE_URL = os.getenv("ALIYUN_VIDEO_API_BASE_URL", "").strip().rstrip("/")
ALIYUN_VIDEO_API_KEY = os.getenv("ALIYUN_VIDEO_API_KEY", "").strip()
FILE_VALIDATION_MAX_COMPRESSION_RATIO = positive_env_int(
    "FILE_VALIDATION_MAX_COMPRESSION_RATIO", 100
)
FILE_IMAGE_MAX_WIDTH = positive_env_int("FILE_IMAGE_MAX_WIDTH", 12000)
FILE_IMAGE_MAX_HEIGHT = positive_env_int("FILE_IMAGE_MAX_HEIGHT", 12000)
FILE_IMAGE_MAX_PIXELS = positive_env_int("FILE_IMAGE_MAX_PIXELS", 80_000_000)
FILE_ALLOWED_APP_ORIGINS = env_list("FILE_ALLOWED_APP_ORIGINS", "http://localhost:3000")
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "http://minio:9000").strip()
S3_REGION = os.getenv("S3_REGION", "us-east-1").strip()
S3_BUCKET = os.getenv("S3_BUCKET", "xianwen-files").strip()
DOCUMENT_OCR_PROVIDER = os.getenv("DOCUMENT_OCR_PROVIDER", "mock").strip().lower()
DOCUMENT_PARSE_MAX_CHARACTERS = positive_env_int("DOCUMENT_PARSE_MAX_CHARACTERS", 2_000_000)
DOCUMENT_PARSE_MAX_UTF8_BYTES = positive_env_int("DOCUMENT_PARSE_MAX_UTF8_BYTES", 8 * 1024 * 1024)
DOCUMENT_PARSE_MAX_TABLES = positive_env_int("DOCUMENT_PARSE_MAX_TABLES", 100)
DOCUMENT_PARSE_MAX_TABLE_ROWS = positive_env_int("DOCUMENT_PARSE_MAX_TABLE_ROWS", 10_000)
DOCUMENT_PARSE_MAX_TABLE_COLUMNS = positive_env_int("DOCUMENT_PARSE_MAX_TABLE_COLUMNS", 200)
DOCUMENT_PARSE_MAX_CELL_CHARACTERS = positive_env_int("DOCUMENT_PARSE_MAX_CELL_CHARACTERS", 10_000)
DOCUMENT_PARSE_MAX_TABLE_JSON_BYTES = positive_env_int(
    "DOCUMENT_PARSE_MAX_TABLE_JSON_BYTES", 8 * 1024 * 1024
)
DOCUMENT_PARSE_RETRY_BASE_SECONDS = positive_env_int("DOCUMENT_PARSE_RETRY_BASE_SECONDS", 30)
DOCUMENT_PARSE_RUNNING_STALE_SECONDS = positive_env_int("DOCUMENT_PARSE_RUNNING_STALE_SECONDS", 600)
DOCUMENT_PARSE_INTERNAL_MAX_RETRIES = positive_env_int("DOCUMENT_PARSE_INTERNAL_MAX_RETRIES", 3)
if DOCUMENT_PARSE_INTERNAL_MAX_RETRIES > 10:
    raise ImproperlyConfigured("DOCUMENT_PARSE_INTERNAL_MAX_RETRIES must not exceed 10.")
WEB_IMPORT_ENABLED = env_bool("WEB_IMPORT_ENABLED", True)
WEB_IMPORT_NETWORK_POLICY_ENFORCED = env_bool("WEB_IMPORT_NETWORK_POLICY_ENFORCED", True)
WEB_IMPORT_IDEMPOTENCY_HMAC_KEY = os.getenv(
    "WEB_IMPORT_IDEMPOTENCY_HMAC_KEY",
    "local-test-web-import-idempotency-key-not-for-production",
).strip()
if len(WEB_IMPORT_IDEMPOTENCY_HMAC_KEY) < 32:
    raise ImproperlyConfigured("WEB_IMPORT_IDEMPOTENCY_HMAC_KEY is too weak; minimum length is 32.")
WEB_IMPORT_MAX_URL_BYTES = positive_env_int("WEB_IMPORT_MAX_URL_BYTES", 4096)
WEB_IMPORT_MAX_REDIRECTS = int(os.getenv("WEB_IMPORT_MAX_REDIRECTS", "5"))
if WEB_IMPORT_MAX_REDIRECTS < 0 or WEB_IMPORT_MAX_REDIRECTS > 10:
    raise ImproperlyConfigured("WEB_IMPORT_MAX_REDIRECTS must be between 0 and 10.")
WEB_IMPORT_CONNECT_TIMEOUT_SECONDS = positive_env_int("WEB_IMPORT_CONNECT_TIMEOUT_SECONDS", 3)
WEB_IMPORT_READ_TIMEOUT_SECONDS = positive_env_int("WEB_IMPORT_READ_TIMEOUT_SECONDS", 10)
WEB_IMPORT_TOTAL_TIMEOUT_SECONDS = positive_env_int("WEB_IMPORT_TOTAL_TIMEOUT_SECONDS", 20)
WEB_IMPORT_MAX_RESPONSE_BYTES = positive_env_int("WEB_IMPORT_MAX_RESPONSE_BYTES", 2 * 1024 * 1024)
WEB_IMPORT_MAX_TEXT_CHARACTERS = positive_env_int("WEB_IMPORT_MAX_TEXT_CHARACTERS", 500_000)
WEB_IMPORT_MAX_HEADER_COUNT = positive_env_int("WEB_IMPORT_MAX_HEADER_COUNT", 100)
WEB_IMPORT_MAX_HEADER_LINE_BYTES = positive_env_int("WEB_IMPORT_MAX_HEADER_LINE_BYTES", 8192)
WEB_IMPORT_MAX_HEADER_BYTES = positive_env_int("WEB_IMPORT_MAX_HEADER_BYTES", 65_536)
WEB_IMPORT_RUNNING_STALE_SECONDS = positive_env_int("WEB_IMPORT_RUNNING_STALE_SECONDS", 120)
WEB_IMPORT_RETRY_BASE_SECONDS = positive_env_int("WEB_IMPORT_RETRY_BASE_SECONDS", 30)
WEB_IMPORT_INTERNAL_MAX_RETRIES = positive_env_int("WEB_IMPORT_INTERNAL_MAX_RETRIES", 3)
if WEB_IMPORT_INTERNAL_MAX_RETRIES > 10:
    raise ImproperlyConfigured("WEB_IMPORT_INTERNAL_MAX_RETRIES must not exceed 10.")
WEB_IMPORT_RATE_LIMIT_WINDOW_SECONDS = positive_env_int(
    "WEB_IMPORT_RATE_LIMIT_WINDOW_SECONDS", 3600
)
WEB_IMPORT_RATE_LIMIT_USER = positive_env_int("WEB_IMPORT_RATE_LIMIT_USER", 30)
WEB_IMPORT_RATE_LIMIT_IP = positive_env_int("WEB_IMPORT_RATE_LIMIT_IP", 60)
WEB_IMPORT_RATE_LIMIT_SUBJECT = positive_env_int("WEB_IMPORT_RATE_LIMIT_SUBJECT", 30)
WEB_IMPORT_RATE_LIMIT_HOST = positive_env_int("WEB_IMPORT_RATE_LIMIT_HOST", 20)
WEB_IMPORT_USER_AGENT = os.getenv("WEB_IMPORT_USER_AGENT", "XianwenWebImporter/1.0").strip()
WEB_IMPORT_TEST_ALLOWED_CIDRS: tuple = ()
ARTICLE_IDEMPOTENCY_HMAC_KEY = os.getenv(
    "ARTICLE_IDEMPOTENCY_HMAC_KEY",
    "local-test-article-idempotency-key-not-for-production",
).strip()
if len(ARTICLE_IDEMPOTENCY_HMAC_KEY) < 32:
    raise ImproperlyConfigured("ARTICLE_IDEMPOTENCY_HMAC_KEY is too weak; minimum length is 32.")
REPORT_SHARE_HMAC_KEY = os.getenv(
    "REPORT_SHARE_HMAC_KEY",
    "local-test-report-share-hmac-key-not-for-production",
).strip()
if len(REPORT_SHARE_HMAC_KEY) < 32:
    raise ImproperlyConfigured("REPORT_SHARE_HMAC_KEY is too weak; minimum length is 32.")
REPORT_SHARE_SESSION_TTL_SECONDS = positive_env_int("REPORT_SHARE_SESSION_TTL_SECONDS", 1800)
REPORT_SHARE_MAX_EXPIRY_DAYS = positive_env_int("REPORT_SHARE_MAX_EXPIRY_DAYS", 365)
ARTICLE_COMPARISON_TTL_SECONDS = positive_env_int("ARTICLE_COMPARISON_TTL_SECONDS", 86400)
SUBJECT_ENRICHMENT_PROVIDER = (
    os.getenv("SUBJECT_ENRICHMENT_PROVIDER", "unavailable").strip().lower()
)
SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY = os.getenv(
    "SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY",
    "local-test-subject-enrichment-idempotency-key-not-for-production",
).strip()
if len(SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY) < 32:
    raise ImproperlyConfigured(
        "SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY is too weak; minimum length is 32."
    )
SUBJECT_ENRICHMENT_MAX_SOURCES = positive_env_int("SUBJECT_ENRICHMENT_MAX_SOURCES", 8)
SUBJECT_ENRICHMENT_MAX_SOURCE_CHARACTERS = positive_env_int(
    "SUBJECT_ENRICHMENT_MAX_SOURCE_CHARACTERS", 20_000
)
SUBJECT_ENRICHMENT_MAX_TOTAL_SOURCE_CHARACTERS = positive_env_int(
    "SUBJECT_ENRICHMENT_MAX_TOTAL_SOURCE_CHARACTERS", 80_000
)
SUBJECT_ENRICHMENT_MAX_TARGET_FIELDS = positive_env_int("SUBJECT_ENRICHMENT_MAX_TARGET_FIELDS", 20)
SUBJECT_ENRICHMENT_PROVIDER_TIMEOUT_SECONDS = positive_env_int(
    "SUBJECT_ENRICHMENT_PROVIDER_TIMEOUT_SECONDS", 30
)
SUBJECT_ENRICHMENT_MAX_PROVIDER_ATTEMPTS = positive_env_int(
    "SUBJECT_ENRICHMENT_MAX_PROVIDER_ATTEMPTS", 3
)
if SUBJECT_ENRICHMENT_MAX_PROVIDER_ATTEMPTS > 10:
    raise ImproperlyConfigured("SUBJECT_ENRICHMENT_MAX_PROVIDER_ATTEMPTS must not exceed 10.")
SUBJECT_ENRICHMENT_RETRY_BASE_SECONDS = positive_env_int(
    "SUBJECT_ENRICHMENT_RETRY_BASE_SECONDS", 30
)
SUBJECT_ENRICHMENT_RUNNING_STALE_SECONDS = positive_env_int(
    "SUBJECT_ENRICHMENT_RUNNING_STALE_SECONDS", 120
)
SUBJECT_ENRICHMENT_INTERNAL_MAX_RETRIES = positive_env_int(
    "SUBJECT_ENRICHMENT_INTERNAL_MAX_RETRIES", 3
)
if SUBJECT_ENRICHMENT_INTERNAL_MAX_RETRIES > 10:
    raise ImproperlyConfigured("SUBJECT_ENRICHMENT_INTERNAL_MAX_RETRIES must not exceed 10.")
SUBJECT_ENRICHMENT_RATE_LIMIT_WINDOW_SECONDS = positive_env_int(
    "SUBJECT_ENRICHMENT_RATE_LIMIT_WINDOW_SECONDS", 3600
)
SUBJECT_ENRICHMENT_RATE_LIMIT_USER = positive_env_int("SUBJECT_ENRICHMENT_RATE_LIMIT_USER", 30)
SUBJECT_ENRICHMENT_RATE_LIMIT_IP = positive_env_int("SUBJECT_ENRICHMENT_RATE_LIMIT_IP", 60)
SUBJECT_ENRICHMENT_RATE_LIMIT_SUBJECT = positive_env_int(
    "SUBJECT_ENRICHMENT_RATE_LIMIT_SUBJECT", 30
)
SUBJECT_ENRICHMENT_MOCK_SCENARIO = (
    os.getenv("SUBJECT_ENRICHMENT_MOCK_SCENARIO", "success").strip().lower()
)
KEYWORD_GENERATION_PROVIDER = (
    os.getenv("KEYWORD_GENERATION_PROVIDER", "unavailable").strip().lower()
)
KEYWORD_GENERATION_IDEMPOTENCY_HMAC_KEY = os.getenv(
    "KEYWORD_GENERATION_IDEMPOTENCY_HMAC_KEY",
    "local-test-keyword-generation-idempotency-key-not-for-production",
).strip()
if len(KEYWORD_GENERATION_IDEMPOTENCY_HMAC_KEY) < 32:
    raise ImproperlyConfigured(
        "KEYWORD_GENERATION_IDEMPOTENCY_HMAC_KEY is too weak; minimum length is 32."
    )
KEYWORD_GENERATION_MAX_COUNT = positive_env_int("KEYWORD_GENERATION_MAX_COUNT", 200)
KEYWORD_GENERATION_MAX_REGIONS = positive_env_int("KEYWORD_GENERATION_MAX_REGIONS", 20)
KEYWORD_GENERATION_PROVIDER_TIMEOUT_SECONDS = positive_env_int(
    "KEYWORD_GENERATION_PROVIDER_TIMEOUT_SECONDS", 30
)
KEYWORD_GENERATION_MAX_PROVIDER_ATTEMPTS = positive_env_int(
    "KEYWORD_GENERATION_MAX_PROVIDER_ATTEMPTS", 3
)
if KEYWORD_GENERATION_MAX_PROVIDER_ATTEMPTS > 10:
    raise ImproperlyConfigured("KEYWORD_GENERATION_MAX_PROVIDER_ATTEMPTS must not exceed 10.")
KEYWORD_GENERATION_RETRY_BASE_SECONDS = positive_env_int(
    "KEYWORD_GENERATION_RETRY_BASE_SECONDS", 30
)
KEYWORD_GENERATION_RUNNING_STALE_SECONDS = positive_env_int(
    "KEYWORD_GENERATION_RUNNING_STALE_SECONDS", 120
)
KEYWORD_GENERATION_INTERNAL_MAX_RETRIES = positive_env_int(
    "KEYWORD_GENERATION_INTERNAL_MAX_RETRIES", 3
)
if KEYWORD_GENERATION_INTERNAL_MAX_RETRIES > 10:
    raise ImproperlyConfigured("KEYWORD_GENERATION_INTERNAL_MAX_RETRIES must not exceed 10.")
KEYWORD_GENERATION_MOCK_SCENARIO = (
    os.getenv("KEYWORD_GENERATION_MOCK_SCENARIO", "success").strip().lower()
)
DISTILLATION_PROVIDER = os.getenv("DISTILLATION_PROVIDER", "unavailable").strip().lower()
DISTILLATION_IDEMPOTENCY_HMAC_KEY = os.getenv(
    "DISTILLATION_IDEMPOTENCY_HMAC_KEY",
    "local-test-distillation-idempotency-key-not-for-production",
).strip()
if len(DISTILLATION_IDEMPOTENCY_HMAC_KEY) < 32:
    raise ImproperlyConfigured(
        "DISTILLATION_IDEMPOTENCY_HMAC_KEY is too weak; minimum length is 32."
    )
DISTILLATION_PROVIDER_TIMEOUT_SECONDS = positive_env_int(
    "DISTILLATION_PROVIDER_TIMEOUT_SECONDS", 30
)
DISTILLATION_MAX_PROVIDER_ATTEMPTS = positive_env_int("DISTILLATION_MAX_PROVIDER_ATTEMPTS", 3)
if DISTILLATION_MAX_PROVIDER_ATTEMPTS > 10:
    raise ImproperlyConfigured("DISTILLATION_MAX_PROVIDER_ATTEMPTS must not exceed 10.")
DISTILLATION_RETRY_BASE_SECONDS = positive_env_int("DISTILLATION_RETRY_BASE_SECONDS", 30)
DISTILLATION_RUNNING_STALE_SECONDS = positive_env_int("DISTILLATION_RUNNING_STALE_SECONDS", 120)
DISTILLATION_INTERNAL_MAX_RETRIES = positive_env_int("DISTILLATION_INTERNAL_MAX_RETRIES", 3)
if DISTILLATION_INTERNAL_MAX_RETRIES > 10:
    raise ImproperlyConfigured("DISTILLATION_INTERNAL_MAX_RETRIES must not exceed 10.")
DISTILLATION_MOCK_SCENARIO = os.getenv("DISTILLATION_MOCK_SCENARIO", "success").strip().lower()
QUESTION_GENERATION_PROVIDER = (
    os.getenv("QUESTION_GENERATION_PROVIDER", "unavailable").strip().lower()
)
QUESTION_GENERATION_IDEMPOTENCY_HMAC_KEY = os.getenv(
    "QUESTION_GENERATION_IDEMPOTENCY_HMAC_KEY",
    "local-test-question-generation-idempotency-key-not-for-production",
).strip()
if len(QUESTION_GENERATION_IDEMPOTENCY_HMAC_KEY) < 32:
    raise ImproperlyConfigured(
        "QUESTION_GENERATION_IDEMPOTENCY_HMAC_KEY is too weak; minimum length is 32."
    )
QUESTION_GENERATION_PROVIDER_TIMEOUT_SECONDS = positive_env_int(
    "QUESTION_GENERATION_PROVIDER_TIMEOUT_SECONDS", 30
)
QUESTION_GENERATION_MAX_PROVIDER_ATTEMPTS = positive_env_int(
    "QUESTION_GENERATION_MAX_PROVIDER_ATTEMPTS", 3
)
if QUESTION_GENERATION_MAX_PROVIDER_ATTEMPTS > 10:
    raise ImproperlyConfigured("QUESTION_GENERATION_MAX_PROVIDER_ATTEMPTS must not exceed 10.")
QUESTION_GENERATION_RETRY_BASE_SECONDS = positive_env_int(
    "QUESTION_GENERATION_RETRY_BASE_SECONDS", 30
)
QUESTION_GENERATION_RUNNING_STALE_SECONDS = positive_env_int(
    "QUESTION_GENERATION_RUNNING_STALE_SECONDS", 120
)
QUESTION_GENERATION_INTERNAL_MAX_RETRIES = positive_env_int(
    "QUESTION_GENERATION_INTERNAL_MAX_RETRIES", 3
)
if QUESTION_GENERATION_INTERNAL_MAX_RETRIES > 10:
    raise ImproperlyConfigured("QUESTION_GENERATION_INTERNAL_MAX_RETRIES must not exceed 10.")
QUESTION_GENERATION_MOCK_SCENARIO = (
    os.getenv("QUESTION_GENERATION_MOCK_SCENARIO", "success").strip().lower()
)
LOCAL_FIELD_ENCRYPTION_MASTER_KEY = base64.urlsafe_b64encode(
    hashlib.sha256(b"xianwen-local-field-encryption-key-not-for-production").digest()
).decode("ascii")
FIELD_ENCRYPTION_MASTER_KEY = os.getenv(
    "FIELD_ENCRYPTION_MASTER_KEY", LOCAL_FIELD_ENCRYPTION_MASTER_KEY
).strip()
API_CREDENTIAL_ENVIRONMENT = os.getenv("API_CREDENTIAL_ENVIRONMENT", "staging").strip().lower()
if API_CREDENTIAL_ENVIRONMENT not in {"staging", "production"}:
    raise ImproperlyConfigured("API_CREDENTIAL_ENVIRONMENT must be staging or production.")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "xianwen-local").strip()
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "xianwen-local-secret").strip()
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
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_SOFT_TIME_LIMIT = 50
CELERY_TASK_TIME_LIMIT = 60
CELERY_BEAT_SCHEDULE = {
    "scan-due-renewals": {
        "task": "plans.scan_due_renewals",
        "schedule": timedelta(seconds=60),
    },
    "scan-due-expiries": {
        "task": "plans.scan_due_expiries",
        "schedule": timedelta(seconds=60),
    },
    "scan-due-quota-cycles": {
        "task": "quotas.scan_due_cycles",
        "schedule": timedelta(seconds=60),
    },
    "scan-expired-file-upload-intents": {
        "task": "documents.scan_expired_upload_intents",
        "schedule": timedelta(seconds=60),
    },
    "scan-file-verification-retries": {
        "task": "documents.scan_verification_retries",
        "schedule": timedelta(seconds=60),
    },
    "scan-document-parse-retries": {
        "task": "documents.scan_parse_retries",
        "schedule": timedelta(seconds=60),
    },
    "dispatch-subject-enrichment-jobs": {
        "task": "subjects.dispatch_enrichment_jobs",
        "schedule": timedelta(seconds=60),
    },
    "dispatch-keyword-generation-jobs": {
        "task": "keywords.dispatch_generation_jobs",
        "schedule": timedelta(seconds=60),
    },
    "dispatch-distillation-jobs": {
        "task": "keywords.dispatch_distillation_jobs",
        "schedule": timedelta(seconds=60),
    },
    "dispatch-question-generation-jobs": {
        "task": "questions.dispatch_generation_jobs",
        "schedule": timedelta(seconds=60),
    },
    "dispatch-video-generation-jobs": {
        "task": "videos.dispatch_due_jobs",
        "schedule": timedelta(seconds=60),
    },
    "dispatch-geo-detection-calls": {
        "task": "geo.dispatch_model_calls",
        "schedule": timedelta(seconds=5),
    },
    "dispatch-queued-web-imports": {
        "task": "web_sources.dispatch_queued_imports",
        "schedule": timedelta(seconds=60),
    },
    "scan-web-import-retries": {
        "task": "web_sources.scan_import_retries",
        "schedule": timedelta(seconds=60),
    },
    "publishing-recover-interrupted": {
        "task": "publishing.recover_interrupted",
        "schedule": timedelta(seconds=300),
    },
}
CELERY_TASK_ROUTES = {
    "subjects.execute_enrichment": {"queue": "ai_content"},
    "keywords.execute_generation": {"queue": "ai_content"},
    "keywords.execute_distillation": {"queue": "ai_content"},
    "questions.execute_generation": {"queue": "ai_content"},
    "geo.execute_strategy_report": {"queue": "ai_content"},
    "websites.execute_generation_job": {"queue": "ai_content"},
    "geo.execute_model_call": {"queue": "geo_detection"},
    "documents.execute_parse_job": {"queue": "file_processing"},
    "web_sources.execute_import": {"queue": "web_fetch"},
    "images.execute_generation": {"queue": "image_generation"},
    "videos.execute_generation": {"queue": "image_generation"},
    "videos.dispatch_due_jobs": {"queue": "image_generation"},
}

CELERY_PRODUCTION_QUEUES = tuple(
    dict.fromkeys(
        (
            CELERY_TASK_DEFAULT_QUEUE,
            *(route["queue"] for route in CELERY_TASK_ROUTES.values()),
        )
    )
)

RELEASE_EXPECTED_WORKER_QUEUES = tuple(
    env_list(
        "RELEASE_EXPECTED_WORKER_QUEUES",
        ",".join(CELERY_PRODUCTION_QUEUES),
    )
)
if not RELEASE_EXPECTED_WORKER_QUEUES or len(set(RELEASE_EXPECTED_WORKER_QUEUES)) != len(
    RELEASE_EXPECTED_WORKER_QUEUES
):
    raise ImproperlyConfigured("RELEASE_EXPECTED_WORKER_QUEUES must be non-empty and unique.")
if set(RELEASE_EXPECTED_WORKER_QUEUES) != set(CELERY_PRODUCTION_QUEUES):
    raise ImproperlyConfigured(
        "RELEASE_EXPECTED_WORKER_QUEUES must exactly match production-routed Celery queues."
    )

RELEASE_DEPLOY_SHA = os.getenv("RELEASE_DEPLOY_SHA", "").strip().lower()
RELEASE_EXPECTED_EXTERNAL_EVIDENCE = tuple(
    env_list(
        "RELEASE_EXPECTED_EXTERNAL_EVIDENCE",
        (
            "cos_private_read_write_delete,sms_delivery,deepseek_geo_detection,"
            "doubao_geo_detection,qwen_geo_detection,hunyuan_geo_detection,"
            "wenxin_geo_detection,kimi_geo_detection,glm_geo_detection,"
            "spark_geo_detection,doubao_image_generation"
        ),
    )
)
if not RELEASE_EXPECTED_EXTERNAL_EVIDENCE or len(set(RELEASE_EXPECTED_EXTERNAL_EVIDENCE)) != len(
    RELEASE_EXPECTED_EXTERNAL_EVIDENCE
):
    raise ImproperlyConfigured("RELEASE_EXPECTED_EXTERNAL_EVIDENCE must be non-empty and unique.")
