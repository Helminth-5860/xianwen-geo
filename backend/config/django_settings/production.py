# ruff: noqa: F403, F405
import os
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured

from apps.core.logging import build_logging_config

from .base import *

APP_ENV = "production"

SECRET_KEY = require_env("DJANGO_SECRET_KEY")
SMS_VERIFICATION_HMAC_KEY = require_env("SMS_VERIFICATION_HMAC_KEY")
QUOTA_IDEMPOTENCY_HMAC_KEY = require_env("QUOTA_IDEMPOTENCY_HMAC_KEY")
GEO_DETECTION_IDEMPOTENCY_HMAC_KEY = require_env("GEO_DETECTION_IDEMPOTENCY_HMAC_KEY")
PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY = require_env("PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY")
FILE_IDEMPOTENCY_HMAC_KEY = require_env("FILE_IDEMPOTENCY_HMAC_KEY")
IMAGE_IDEMPOTENCY_HMAC_KEY = require_env("IMAGE_IDEMPOTENCY_HMAC_KEY")
WEB_IMPORT_IDEMPOTENCY_HMAC_KEY = require_env("WEB_IMPORT_IDEMPOTENCY_HMAC_KEY")
SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY = require_env("SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY")
KEYWORD_GENERATION_IDEMPOTENCY_HMAC_KEY = require_env("KEYWORD_GENERATION_IDEMPOTENCY_HMAC_KEY")
DISTILLATION_IDEMPOTENCY_HMAC_KEY = require_env("DISTILLATION_IDEMPOTENCY_HMAC_KEY")
ARTICLE_IDEMPOTENCY_HMAC_KEY = require_env("ARTICLE_IDEMPOTENCY_HMAC_KEY")
REPORT_SHARE_HMAC_KEY = require_env("REPORT_SHARE_HMAC_KEY")
FIELD_ENCRYPTION_MASTER_KEY = require_env("FIELD_ENCRYPTION_MASTER_KEY")
API_CREDENTIAL_ENVIRONMENT = require_env("API_CREDENTIAL_ENVIRONMENT").lower()
if API_CREDENTIAL_ENVIRONMENT not in {"staging", "production"}:
    raise ImproperlyConfigured("API_CREDENTIAL_ENVIRONMENT must be staging or production.")
try:
    Fernet(FIELD_ENCRYPTION_MASTER_KEY.encode("ascii"))
except (TypeError, ValueError, UnicodeEncodeError) as exc:
    raise ImproperlyConfigured("FIELD_ENCRYPTION_MASTER_KEY must be a valid Fernet key.") from exc
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
if FIELD_ENCRYPTION_MASTER_KEY == LOCAL_FIELD_ENCRYPTION_MASTER_KEY:
    raise ImproperlyConfigured("FIELD_ENCRYPTION_MASTER_KEY must not use the local default.")
if FIELD_ENCRYPTION_MASTER_KEY in {
    SECRET_KEY,
    SMS_VERIFICATION_HMAC_KEY,
    QUOTA_IDEMPOTENCY_HMAC_KEY,
    GEO_DETECTION_IDEMPOTENCY_HMAC_KEY,
    PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY,
    FILE_IDEMPOTENCY_HMAC_KEY,
    IMAGE_IDEMPOTENCY_HMAC_KEY,
    WEB_IMPORT_IDEMPOTENCY_HMAC_KEY,
    SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY,
    KEYWORD_GENERATION_IDEMPOTENCY_HMAC_KEY,
    DISTILLATION_IDEMPOTENCY_HMAC_KEY,
    QUESTION_GENERATION_IDEMPOTENCY_HMAC_KEY,
    ARTICLE_IDEMPOTENCY_HMAC_KEY,
    REPORT_SHARE_HMAC_KEY,
}:
    raise ImproperlyConfigured("FIELD_ENCRYPTION_MASTER_KEY must be independent.")
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
if (
    len(GEO_DETECTION_IDEMPOTENCY_HMAC_KEY) < 50
    or GEO_DETECTION_IDEMPOTENCY_HMAC_KEY.lower() in weak_secret_markers
):
    raise ImproperlyConfigured("GEO_DETECTION_IDEMPOTENCY_HMAC_KEY is too weak for production.")
if GEO_DETECTION_IDEMPOTENCY_HMAC_KEY in {
    SECRET_KEY,
    SMS_VERIFICATION_HMAC_KEY,
    QUOTA_IDEMPOTENCY_HMAC_KEY,
}:
    raise ImproperlyConfigured(
        "GEO_DETECTION_IDEMPOTENCY_HMAC_KEY must not reuse another application secret."
    )
if (
    len(PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY) < 50
    or PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY.lower() in weak_secret_markers
):
    raise ImproperlyConfigured("PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY is too weak for production.")
if PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY in {
    SECRET_KEY,
    SMS_VERIFICATION_HMAC_KEY,
    QUOTA_IDEMPOTENCY_HMAC_KEY,
    GEO_DETECTION_IDEMPOTENCY_HMAC_KEY,
}:
    raise ImproperlyConfigured(
        "PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY must not reuse another application secret."
    )
if len(FILE_IDEMPOTENCY_HMAC_KEY) < 50 or FILE_IDEMPOTENCY_HMAC_KEY.lower() in weak_secret_markers:
    raise ImproperlyConfigured("FILE_IDEMPOTENCY_HMAC_KEY is too weak for production.")
if FILE_IDEMPOTENCY_HMAC_KEY in {
    SECRET_KEY,
    SMS_VERIFICATION_HMAC_KEY,
    QUOTA_IDEMPOTENCY_HMAC_KEY,
    PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY,
}:
    raise ImproperlyConfigured("FILE_IDEMPOTENCY_HMAC_KEY must not reuse another secret.")
if (
    len(IMAGE_IDEMPOTENCY_HMAC_KEY) < 50
    or IMAGE_IDEMPOTENCY_HMAC_KEY.lower() in weak_secret_markers
):
    raise ImproperlyConfigured("IMAGE_IDEMPOTENCY_HMAC_KEY is too weak for production.")
if IMAGE_IDEMPOTENCY_HMAC_KEY in {
    SECRET_KEY,
    SMS_VERIFICATION_HMAC_KEY,
    QUOTA_IDEMPOTENCY_HMAC_KEY,
    GEO_DETECTION_IDEMPOTENCY_HMAC_KEY,
    PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY,
    FILE_IDEMPOTENCY_HMAC_KEY,
}:
    raise ImproperlyConfigured("IMAGE_IDEMPOTENCY_HMAC_KEY must not reuse another secret.")
if (
    len(WEB_IMPORT_IDEMPOTENCY_HMAC_KEY) < 50
    or WEB_IMPORT_IDEMPOTENCY_HMAC_KEY.lower() in weak_secret_markers
):
    raise ImproperlyConfigured("WEB_IMPORT_IDEMPOTENCY_HMAC_KEY is too weak for production.")
if WEB_IMPORT_IDEMPOTENCY_HMAC_KEY in {
    SECRET_KEY,
    SMS_VERIFICATION_HMAC_KEY,
    QUOTA_IDEMPOTENCY_HMAC_KEY,
    PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY,
    FILE_IDEMPOTENCY_HMAC_KEY,
    IMAGE_IDEMPOTENCY_HMAC_KEY,
}:
    raise ImproperlyConfigured("WEB_IMPORT_IDEMPOTENCY_HMAC_KEY must not reuse another secret.")

if SUBJECT_ENRICHMENT_PROVIDER == "mock":
    raise ImproperlyConfigured("Mock subject enrichment provider is forbidden in production.")
if SUBJECT_ENRICHMENT_PROVIDER != "unavailable":
    raise ImproperlyConfigured(
        "Only unavailable subject enrichment provider is supported in production."
    )
if len(SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY) < 50:
    raise ImproperlyConfigured(
        "SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY is too weak for production."
    )
for reused in (
    SECRET_KEY,
    SMS_VERIFICATION_HMAC_KEY,
    QUOTA_IDEMPOTENCY_HMAC_KEY,
    PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY,
    FILE_IDEMPOTENCY_HMAC_KEY,
    IMAGE_IDEMPOTENCY_HMAC_KEY,
    WEB_IMPORT_IDEMPOTENCY_HMAC_KEY,
):
    if SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY == reused:
        raise ImproperlyConfigured("SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY must be independent.")

if KEYWORD_GENERATION_PROVIDER == "mock":
    raise ImproperlyConfigured("Mock keyword generation provider is forbidden in production.")
if KEYWORD_GENERATION_PROVIDER not in {"unavailable", "deepseek"}:
    raise ImproperlyConfigured(
        "Only unavailable or deepseek keyword generation provider is supported in production."
    )
if len(KEYWORD_GENERATION_IDEMPOTENCY_HMAC_KEY) < 50:
    raise ImproperlyConfigured(
        "KEYWORD_GENERATION_IDEMPOTENCY_HMAC_KEY is too weak for production."
    )
if KEYWORD_GENERATION_IDEMPOTENCY_HMAC_KEY in {
    SECRET_KEY,
    SMS_VERIFICATION_HMAC_KEY,
    QUOTA_IDEMPOTENCY_HMAC_KEY,
    PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY,
    FILE_IDEMPOTENCY_HMAC_KEY,
    IMAGE_IDEMPOTENCY_HMAC_KEY,
    WEB_IMPORT_IDEMPOTENCY_HMAC_KEY,
    SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY,
}:
    raise ImproperlyConfigured("KEYWORD_GENERATION_IDEMPOTENCY_HMAC_KEY must be independent.")

if DISTILLATION_PROVIDER == "mock":
    raise ImproperlyConfigured("Mock distillation provider is forbidden in production.")
if DISTILLATION_PROVIDER not in {"unavailable", "deepseek"}:
    raise ImproperlyConfigured(
        "Only unavailable or deepseek distillation provider is supported in production."
    )
if len(DISTILLATION_IDEMPOTENCY_HMAC_KEY) < 50:
    raise ImproperlyConfigured("DISTILLATION_IDEMPOTENCY_HMAC_KEY is too weak for production.")
if DISTILLATION_IDEMPOTENCY_HMAC_KEY in {
    SECRET_KEY,
    SMS_VERIFICATION_HMAC_KEY,
    QUOTA_IDEMPOTENCY_HMAC_KEY,
    PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY,
    FILE_IDEMPOTENCY_HMAC_KEY,
    IMAGE_IDEMPOTENCY_HMAC_KEY,
    WEB_IMPORT_IDEMPOTENCY_HMAC_KEY,
    SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY,
    KEYWORD_GENERATION_IDEMPOTENCY_HMAC_KEY,
}:
    raise ImproperlyConfigured("DISTILLATION_IDEMPOTENCY_HMAC_KEY must be independent.")

if QUESTION_GENERATION_PROVIDER == "mock":
    raise ImproperlyConfigured("Mock question generation provider is forbidden in production.")
if QUESTION_GENERATION_PROVIDER != "unavailable":
    raise ImproperlyConfigured(
        "Only unavailable question generation provider is supported in production."
    )
if len(QUESTION_GENERATION_IDEMPOTENCY_HMAC_KEY) < 50:
    raise ImproperlyConfigured(
        "QUESTION_GENERATION_IDEMPOTENCY_HMAC_KEY is too weak for production."
    )
if QUESTION_GENERATION_IDEMPOTENCY_HMAC_KEY in {
    SECRET_KEY,
    SMS_VERIFICATION_HMAC_KEY,
    QUOTA_IDEMPOTENCY_HMAC_KEY,
    PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY,
    FILE_IDEMPOTENCY_HMAC_KEY,
    IMAGE_IDEMPOTENCY_HMAC_KEY,
    WEB_IMPORT_IDEMPOTENCY_HMAC_KEY,
    SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY,
    KEYWORD_GENERATION_IDEMPOTENCY_HMAC_KEY,
    DISTILLATION_IDEMPOTENCY_HMAC_KEY,
}:
    raise ImproperlyConfigured("QUESTION_GENERATION_IDEMPOTENCY_HMAC_KEY must be independent.")

for secret_name, secret_value in (
    ("ARTICLE_IDEMPOTENCY_HMAC_KEY", ARTICLE_IDEMPOTENCY_HMAC_KEY),
    ("REPORT_SHARE_HMAC_KEY", REPORT_SHARE_HMAC_KEY),
):
    lowered_secret = secret_value.lower()
    if (
        len(secret_value) < 50
        or lowered_secret in weak_secret_markers
        or "not-for-production" in lowered_secret
        or "local-test" in lowered_secret
        or "replace-with" in lowered_secret
    ):
        raise ImproperlyConfigured(f"{secret_name} is too weak for production.")
    if secret_value in {
        SECRET_KEY,
        SMS_VERIFICATION_HMAC_KEY,
        QUOTA_IDEMPOTENCY_HMAC_KEY,
        GEO_DETECTION_IDEMPOTENCY_HMAC_KEY,
        PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY,
        FILE_IDEMPOTENCY_HMAC_KEY,
        IMAGE_IDEMPOTENCY_HMAC_KEY,
        WEB_IMPORT_IDEMPOTENCY_HMAC_KEY,
        SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY,
        KEYWORD_GENERATION_IDEMPOTENCY_HMAC_KEY,
        DISTILLATION_IDEMPOTENCY_HMAC_KEY,
        QUESTION_GENERATION_IDEMPOTENCY_HMAC_KEY,
    }:
        raise ImproperlyConfigured(f"{secret_name} must be independent.")
if ARTICLE_IDEMPOTENCY_HMAC_KEY == REPORT_SHARE_HMAC_KEY:
    raise ImproperlyConfigured("Stage 2 HMAC keys must be independent.")

WEB_IMPORT_ENABLED = env_bool("WEB_IMPORT_ENABLED", False)
WEB_IMPORT_NETWORK_POLICY_ENFORCED = env_bool("WEB_IMPORT_NETWORK_POLICY_ENFORCED", False)
if WEB_IMPORT_ENABLED and not WEB_IMPORT_NETWORK_POLICY_ENFORCED:
    raise ImproperlyConfigured("Enabled web import requires enforced production network policy.")
WEB_IMPORT_TEST_ALLOWED_CIDRS = ()
FILE_STORAGE_PROVIDER = os.getenv("FILE_STORAGE_PROVIDER", "unavailable").strip().lower()
FILE_SCANNER_PROVIDER = os.getenv("FILE_SCANNER_PROVIDER", "unavailable").strip().lower()
if FILE_STORAGE_PROVIDER == "mock":
    raise ImproperlyConfigured("Mock file storage provider is forbidden in production.")
if FILE_SCANNER_PROVIDER in {"mock", "always_clean"}:
    raise ImproperlyConfigured("Mock file scanner is forbidden in production.")
if FILE_STORAGE_PROVIDER not in {"s3", "unavailable"}:
    raise ImproperlyConfigured("Unsupported production file storage provider.")
if FILE_SCANNER_PROVIDER not in {"clamav", "unavailable"}:
    raise ImproperlyConfigured("Unsupported production file scanner provider.")
if FILE_SCANNER_PROVIDER == "clamav" and not CLAMAV_HOST:
    raise ImproperlyConfigured("CLAMAV_HOST is required for FILE_SCANNER_PROVIDER=clamav.")
DOCUMENT_OCR_PROVIDER = os.getenv("DOCUMENT_OCR_PROVIDER", "unavailable").strip().lower()
if DOCUMENT_OCR_PROVIDER != "unavailable":
    raise ImproperlyConfigured("Mock or unknown OCR providers are forbidden in production.")
if FILE_STORAGE_PROVIDER == "s3":
    required_s3 = {
        "S3_ENDPOINT_URL": S3_ENDPOINT_URL,
        "S3_REGION": S3_REGION,
        "S3_BUCKET": S3_BUCKET,
        "S3_ACCESS_KEY": S3_ACCESS_KEY,
        "S3_SECRET_KEY": S3_SECRET_KEY,
    }
    missing_s3 = [name for name, value in required_s3.items() if not value]
    if missing_s3:
        raise ImproperlyConfigured(
            "Missing S3-compatible storage settings: " + ", ".join(missing_s3)
        )
    if FILE_IDEMPOTENCY_HMAC_KEY == S3_SECRET_KEY:
        raise ImproperlyConfigured("FILE_IDEMPOTENCY_HMAC_KEY must not reuse S3_SECRET_KEY.")
    if IMAGE_IDEMPOTENCY_HMAC_KEY == S3_SECRET_KEY:
        raise ImproperlyConfigured("IMAGE_IDEMPOTENCY_HMAC_KEY must not reuse S3_SECRET_KEY.")
configured_file_origins = os.getenv("FILE_ALLOWED_APP_ORIGINS", "")
if not configured_file_origins.strip():
    raise ImproperlyConfigured("FILE_ALLOWED_APP_ORIGINS is required.")
FILE_ALLOWED_APP_ORIGINS = env_list("FILE_ALLOWED_APP_ORIGINS")
if any(origin == "*" for origin in FILE_ALLOWED_APP_ORIGINS):
    raise ImproperlyConfigured("Wildcard file application origins are forbidden.")
if any(urlsplit(origin).scheme not in {"http", "https"} for origin in FILE_ALLOWED_APP_ORIGINS):
    raise ImproperlyConfigured("FILE_ALLOWED_APP_ORIGINS must contain HTTP(S) origins.")

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
    if GEO_DETECTION_IDEMPOTENCY_HMAC_KEY in {configured_url, configured_password}:
        raise ImproperlyConfigured(
            f"GEO_DETECTION_IDEMPOTENCY_HMAC_KEY must not reuse {forbidden_variable} credentials."
        )
    if PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY in {configured_url, configured_password}:
        raise ImproperlyConfigured(
            f"PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY must not reuse {forbidden_variable} credentials."
        )

    if FILE_IDEMPOTENCY_HMAC_KEY in {configured_url, configured_password}:
        raise ImproperlyConfigured(
            f"FILE_IDEMPOTENCY_HMAC_KEY must not reuse {forbidden_variable} credentials."
        )
    if WEB_IMPORT_IDEMPOTENCY_HMAC_KEY in {configured_url, configured_password}:
        raise ImproperlyConfigured(
            f"WEB_IMPORT_IDEMPOTENCY_HMAC_KEY must not reuse {forbidden_variable} credentials."
        )
    if SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY in {configured_url, configured_password}:
        raise ImproperlyConfigured(
            "SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY must not reuse "
            f"{forbidden_variable} credentials."
        )
    if KEYWORD_GENERATION_IDEMPOTENCY_HMAC_KEY in {configured_url, configured_password}:
        raise ImproperlyConfigured(
            "KEYWORD_GENERATION_IDEMPOTENCY_HMAC_KEY must not reuse "
            f"{forbidden_variable} credentials."
        )
    if DISTILLATION_IDEMPOTENCY_HMAC_KEY in {configured_url, configured_password}:
        raise ImproperlyConfigured(
            f"DISTILLATION_IDEMPOTENCY_HMAC_KEY must not reuse {forbidden_variable} credentials."
        )
    if QUESTION_GENERATION_IDEMPOTENCY_HMAC_KEY in {configured_url, configured_password}:
        raise ImproperlyConfigured(
            "QUESTION_GENERATION_IDEMPOTENCY_HMAC_KEY must not reuse "
            f"{forbidden_variable} credentials."
        )
    if ARTICLE_IDEMPOTENCY_HMAC_KEY in {configured_url, configured_password}:
        raise ImproperlyConfigured(
            f"ARTICLE_IDEMPOTENCY_HMAC_KEY must not reuse {forbidden_variable} credentials."
        )
    if IMAGE_IDEMPOTENCY_HMAC_KEY in {configured_url, configured_password}:
        raise ImproperlyConfigured(
            f"IMAGE_IDEMPOTENCY_HMAC_KEY must not reuse {forbidden_variable} credentials."
        )
    if REPORT_SHARE_HMAC_KEY in {configured_url, configured_password}:
        raise ImproperlyConfigured(
            f"REPORT_SHARE_HMAC_KEY must not reuse {forbidden_variable} credentials."
        )
    if FIELD_ENCRYPTION_MASTER_KEY in {configured_url, configured_password}:
        raise ImproperlyConfigured(
            f"FIELD_ENCRYPTION_MASTER_KEY must not reuse {forbidden_variable} credentials."
        )
if FILE_STORAGE_PROVIDER == "s3" and FIELD_ENCRYPTION_MASTER_KEY == S3_SECRET_KEY:
    raise ImproperlyConfigured("FIELD_ENCRYPTION_MASTER_KEY must not reuse S3_SECRET_KEY.")
SMS_PROVIDER = os.getenv("SMS_PROVIDER", "unconfigured").strip().lower()
ENABLE_REAL_SMS = env_bool("ENABLE_REAL_SMS", False)
if SMS_PROVIDER == "mock":
    raise ImproperlyConfigured("Mock SMS provider is forbidden in production.")
if SMS_PROVIDER == "tencent":
    if not ENABLE_REAL_SMS:
        raise ImproperlyConfigured("ENABLE_REAL_SMS must be true for SMS_PROVIDER=tencent.")
    required_tencent_sms = {
        "SMS_REGION": SMS_REGION,
        "SMS_APP_ID": SMS_APP_ID,
        "SMS_SECRET_ID": SMS_SECRET_ID,
        "SMS_SECRET_KEY": SMS_SECRET_KEY,
        "SMS_SIGN_NAME": SMS_SIGN_NAME,
        "SMS_TEMPLATE_REGISTER": SMS_TEMPLATE_REGISTER,
        "SMS_TEMPLATE_LOGIN": SMS_TEMPLATE_LOGIN,
        "SMS_TEMPLATE_SECURITY": SMS_TEMPLATE_SECURITY,
    }
    missing_tencent_sms = [name for name, value in required_tencent_sms.items() if not value]
    if missing_tencent_sms:
        raise ImproperlyConfigured(
            "Missing Tencent SMS settings: " + ", ".join(missing_tencent_sms)
        )
elif ENABLE_REAL_SMS:
    raise ImproperlyConfigured("SMS_PROVIDER must be tencent when ENABLE_REAL_SMS is true.")
elif SMS_PROVIDER != "unconfigured":
    raise ImproperlyConfigured("Unsupported production SMS_PROVIDER.")
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

SECURE_REFERRER_POLICY = "no-referrer"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
DATA_UPLOAD_MAX_MEMORY_SIZE = positive_env_int("DATA_UPLOAD_MAX_MEMORY_SIZE", 2 * 1024 * 1024)
FILE_UPLOAD_MAX_MEMORY_SIZE = positive_env_int("FILE_UPLOAD_MAX_MEMORY_SIZE", 2 * 1024 * 1024)

RELEASE_ENFORCE_EXTERNAL_READINESS = env_bool("RELEASE_ENFORCE_EXTERNAL_READINESS", False)
RELEASE_DEPLOY_SHA = os.getenv("RELEASE_DEPLOY_SHA", "").strip().lower()
if RELEASE_DEPLOY_SHA and (
    len(RELEASE_DEPLOY_SHA) != 40
    or any(character not in "0123456789abcdef" for character in RELEASE_DEPLOY_SHA)
):
    raise ImproperlyConfigured("RELEASE_DEPLOY_SHA must be a full lowercase Git SHA.")
if RELEASE_ENFORCE_EXTERNAL_READINESS:
    if not RELEASE_DEPLOY_SHA:
        raise ImproperlyConfigured(
            "RELEASE_DEPLOY_SHA is required when external readiness enforcement is enabled."
        )
    if FILE_STORAGE_PROVIDER != "s3" or FILE_SCANNER_PROVIDER != "clamav":
        raise ImproperlyConfigured(
            "External readiness requires private S3 storage and ClamAV scanning."
        )
    if SMS_PROVIDER != "tencent" or not ENABLE_REAL_SMS:
        raise ImproperlyConfigured("External readiness requires enabled Tencent SMS.")

_release_secrets = {
    "DJANGO_SECRET_KEY": SECRET_KEY,
    "SMS_VERIFICATION_HMAC_KEY": SMS_VERIFICATION_HMAC_KEY,
    "QUOTA_IDEMPOTENCY_HMAC_KEY": QUOTA_IDEMPOTENCY_HMAC_KEY,
    "GEO_DETECTION_IDEMPOTENCY_HMAC_KEY": GEO_DETECTION_IDEMPOTENCY_HMAC_KEY,
    "PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY": PLAN_CHANGE_IDEMPOTENCY_HMAC_KEY,
    "FILE_IDEMPOTENCY_HMAC_KEY": FILE_IDEMPOTENCY_HMAC_KEY,
    "IMAGE_IDEMPOTENCY_HMAC_KEY": IMAGE_IDEMPOTENCY_HMAC_KEY,
    "WEB_IMPORT_IDEMPOTENCY_HMAC_KEY": WEB_IMPORT_IDEMPOTENCY_HMAC_KEY,
    "SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY": SUBJECT_ENRICHMENT_IDEMPOTENCY_HMAC_KEY,
    "KEYWORD_GENERATION_IDEMPOTENCY_HMAC_KEY": KEYWORD_GENERATION_IDEMPOTENCY_HMAC_KEY,
    "DISTILLATION_IDEMPOTENCY_HMAC_KEY": DISTILLATION_IDEMPOTENCY_HMAC_KEY,
    "QUESTION_GENERATION_IDEMPOTENCY_HMAC_KEY": QUESTION_GENERATION_IDEMPOTENCY_HMAC_KEY,
    "ARTICLE_IDEMPOTENCY_HMAC_KEY": ARTICLE_IDEMPOTENCY_HMAC_KEY,
    "REPORT_SHARE_HMAC_KEY": REPORT_SHARE_HMAC_KEY,
    "FIELD_ENCRYPTION_MASTER_KEY": FIELD_ENCRYPTION_MASTER_KEY,
}
if FILE_STORAGE_PROVIDER == "s3":
    _release_secrets["S3_SECRET_KEY"] = S3_SECRET_KEY
if SMS_PROVIDER == "tencent":
    _release_secrets["SMS_SECRET_KEY"] = SMS_SECRET_KEY
_secret_owners: dict[str, str] = {}
for _secret_name, _secret_value in _release_secrets.items():
    if not _secret_value:
        continue
    _previous_owner = _secret_owners.get(_secret_value)
    if _previous_owner:
        raise ImproperlyConfigured(
            f"{_secret_name} must not reuse the value configured for {_previous_owner}."
        )
    _secret_owners[_secret_value] = _secret_name
