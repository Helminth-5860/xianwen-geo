from django.conf import settings
from django.db import connection


def test_only_django_session_authentication_is_enabled():
    assert settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"] == [
        "apps.users.authentication.ApiSessionAuthentication"
    ]
    assert all(
        "BasicAuthentication" not in authentication_class and "JWT" not in authentication_class
        for authentication_class in settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"]
    )


def test_session_and_csrf_cookie_configuration():
    assert settings.SESSION_COOKIE_NAME == "xianwen_session"
    assert settings.SESSION_COOKIE_HTTPONLY is True
    assert settings.SESSION_COOKIE_SAMESITE == "Lax"
    assert settings.SESSION_COOKIE_PATH == "/"
    assert settings.SESSION_COOKIE_DOMAIN is None
    assert settings.SESSION_COOKIE_AGE == 12 * 60 * 60
    assert settings.SESSION_EXPIRE_AT_BROWSER_CLOSE is True
    assert settings.SESSION_SAVE_EVERY_REQUEST is False
    assert settings.CSRF_COOKIE_NAME == "xianwen_csrf"
    assert settings.CSRF_COOKIE_HTTPONLY is False
    assert settings.CSRF_COOKIE_SAMESITE == "Lax"


def test_frozen_login_rate_limit_defaults():
    assert settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS == 900
    assert settings.LOGIN_RATE_LIMIT_LOCK_SECONDS == 900
    assert settings.LOGIN_RATE_LIMIT_COMBINATION_FAILURES == 5
    assert settings.LOGIN_RATE_LIMIT_PHONE_FAILURES == 10
    assert settings.LOGIN_RATE_LIMIT_IP_FAILURES == 30


def test_fresh_migration_uses_custom_user_without_auth_user_table(db):
    tables = set(connection.introspection.table_names())

    assert settings.AUTH_USER_MODEL == "users.User"
    assert "users" in tables
    assert "login_events" in tables
    assert "auth_user" not in tables
    assert "django_session" in tables
    assert "auth_permission" in tables
