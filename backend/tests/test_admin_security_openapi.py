from pathlib import Path

import yaml

OPENAPI_PATH = Path(__file__).resolve().parents[2] / "openapi" / "openapi-v1.yaml"


def specification():
    return yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))


def test_admin_security_openapi_registers_all_frozen_paths_and_methods():
    paths = specification()["paths"]
    expected = {
        "/admin/auth/login/password": {"post"},
        "/admin/auth/step-up/challenge": {"post"},
        "/admin/auth/step-up/verify": {"post"},
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


def test_admin_security_openapi_marks_only_request_secrets_write_only():
    schemas = specification()["components"]["schemas"]
    assert schemas["AdminPasswordLoginRequest"]["properties"]["password"]["writeOnly"] is True
    assert schemas["AdminStepUpVerifyRequest"]["properties"]["challenge_id"]["writeOnly"] is True
    assert schemas["SecurityMutationBase"]["properties"]["current_password"]["writeOnly"] is True

    response_data = schemas["AdminPasswordLoginEnvelope"]["allOf"][1]["properties"]["data"]
    assert response_data["properties"]["requires_2fa"]["const"] is False
    assert response_data["required"] == ["requires_2fa", "user"]


def test_admin_security_openapi_sms_code_pattern_requires_exactly_six_digits():
    schemas = specification()["components"]["schemas"]
    sms_code = schemas["AdminStepUpVerifyRequest"]["properties"]["sms_code"]
    assert sms_code["pattern"] == "^[0-9]{6}$"
    assert sms_code["writeOnly"] is True


def test_admin_security_openapi_response_matrices_are_complete():
    paths = specification()["paths"]
    expected = {
        ("/admin/auth/login/password", "post"): {"200", "401", "403", "422", "429", "503", "500"},
        ("/admin/auth/step-up/challenge", "post"): {"201", "403", "429", "503", "500"},
        ("/admin/auth/step-up/verify", "post"): {"200", "401", "403", "422", "503", "500"},
        ("/admin/auth/logout", "post"): {"200", "401", "403", "500"},
        ("/admin/roles/{roleId}/security", "get"): {"200", "403", "404", "500"},
        ("/admin/roles/{roleId}/security", "patch"): {
            "200",
            "403",
            "404",
            "409",
            "422",
            "429",
            "503",
            "500",
        },
        ("/admin/roles/{roleId}/ip-allowlist", "get"): {"200", "403", "404", "500"},
        ("/admin/roles/{roleId}/ip-allowlist", "post"): {
            "201",
            "403",
            "404",
            "409",
            "422",
            "429",
            "503",
            "500",
        },
        ("/admin/roles/{roleId}/ip-allowlist/{entryId}", "patch"): {
            "200",
            "403",
            "404",
            "409",
            "422",
            "429",
            "503",
            "500",
        },
        ("/admin/security/superuser", "get"): {"200", "403", "500"},
        ("/admin/security/superuser", "patch"): {"200", "403", "409", "422", "429", "503", "500"},
        ("/admin/security/superuser/ip-allowlist", "get"): {"200", "403", "500"},
        ("/admin/security/superuser/ip-allowlist", "post"): {
            "201",
            "403",
            "409",
            "422",
            "429",
            "503",
            "500",
        },
        ("/admin/security/superuser/ip-allowlist/{entryId}", "patch"): {
            "200",
            "403",
            "404",
            "409",
            "422",
            "429",
            "503",
            "500",
        },
        ("/admin/admins/{adminId}/force-logout", "post"): {
            "200",
            "401",
            "403",
            "404",
            "422",
            "500",
        },
    }
    for (path, method), statuses in expected.items():
        assert set(paths[path][method]["responses"]) == statuses


def test_admin_security_openapi_has_stable_errors_without_sensitive_response_fields():
    schemas = specification()["components"]["schemas"]
    errors = set(schemas["ErrorCode"]["enum"])
    assert {
        "ADMIN_LOGIN_REQUIRED",
        "ADMIN_AUTH_CHALLENGE_INVALID",
        "ADMIN_AUTH_CHALLENGE_EXPIRED",
        "ADMIN_STEP_UP_REQUIRED",
        "ADMIN_STEP_UP_EXPIRED",
        "ADMIN_IP_NOT_ALLOWED",
        "ADMIN_REAUTH_FAILED",
        "SECURITY_POLICY_VERSION_CONFLICT",
        "IP_ALLOWLIST_LOCKOUT_CONFIRMATION_REQUIRED",
    }.issubset(errors)

    response_properties = schemas["AdminPasswordLoginEnvelope"]["allOf"][1]["properties"]["data"][
        "properties"
    ]
    assert not (
        {"password", "current_password", "sms_code", "phone", "network_cidr"}
        & response_properties.keys()
    )
