# ruff: noqa: F403, F405
import os
from ipaddress import ip_network

from apps.core.logging import build_logging_config

from .base import *

APP_ENV = "test"
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
CSRF_TRUSTED_ORIGINS = ["http://testserver"]
CORS_ALLOWED_ORIGINS = ["http://testserver"]
DATABASES = {"default": database_from_url(os.environ["DATABASE_URL"], conn_max_age=0)}
DATABASES["default"]["TEST"] = {"NAME": DATABASES["default"]["NAME"]}
CACHES = {"default": redis_cache(os.environ["REDIS_URL"])}
CELERY_BROKER_URL = os.environ["CELERY_BROKER_URL"]
WEB_IMPORT_ENABLED = True
WEB_IMPORT_NETWORK_POLICY_ENFORCED = True
WEB_IMPORT_IDEMPOTENCY_HMAC_KEY = os.environ["WEB_IMPORT_IDEMPOTENCY_HMAC_KEY"]
WEB_IMPORT_TEST_ALLOWED_CIDRS = (ip_network("172.31.207.0/24"),)
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
LOGGING = build_logging_config("test")
