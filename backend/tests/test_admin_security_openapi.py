from pathlib import Path

import yaml

OPENAPI_PATH = Path(__file__).resolve().parents[2] / "openapi" / "openapi-v1.yaml"


def specification():
    return yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))


def test_admin_security_openapi_registers_all_frozen_paths_and_methods():
    paths = specification()["paths"]
    expected = {
        "/admin/auth/login/password": {"post"},
        "/admin/auth/login/sms/send": {"post"},
        "/admin/auth/login/sms/verify": {"post"},
        "/admin/auth/logout": {"post"},
        "/admin/roles/{roleId}/security": {"get", "patch"},
        "/admin/roles/{roleId}/ip-allowlist": {"get", "post"},
        "/admin/roles/{roleId}/ip-allowlist/{entryId}": {"patch"},
        "/admin/security/superuser": {"get", "patch"},
        "/admin/security/superuser/ip-allowlist": {"get", "post"},
        "/admin/security/superuser/ip-allowlist/{entryId}": {"patch"},
        "/admin/admins/{adminId}/force-logout": {"post"},
    }
    for path, methods in expected.items():
        assert path in paths
        assert methods.issubset(paths[path])


def test_admin_security_openapi_has_sensitive_write_only_fields_and_stable_errors():
    schemas = specification()["components"]["schemas"]
    errors = set(schemas["ErrorCode"]["enum"])
    assert schemas["AdminPasswordLoginRequest"]["properties"]["password"]["writeOnly"] is True
    assert schemas["AdminChallengeRequest"]["properties"]["challenge_id"]["writeOnly"] is True
    assert schemas["SecurityMutationBase"]["properties"]["current_password"]["writeOnly"] is True
    assert {
        "ADMIN_LOGIN_REQUIRED",
        "ADMIN_AUTH_CHALLENGE_INVALID",
        "ADMIN_AUTH_CHALLENGE_EXPIRED",
        "ADMIN_IP_NOT_ALLOWED",
        "ADMIN_REAUTH_FAILED",
        "SECURITY_POLICY_VERSION_CONFLICT",
        "IP_ALLOWLIST_LOCKOUT_CONFIRMATION_REQUIRED",
    }.issubset(errors)
