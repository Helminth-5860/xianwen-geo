from pathlib import Path

from yaml import safe_load


def load_openapi():
    path = Path(__file__).resolve().parents[2] / "openapi" / "openapi-v1.yaml"
    return safe_load(path.read_text(encoding="utf-8"))


def test_openapi_exposes_only_implemented_auth_endpoints():
    specification = load_openapi()
    paths = specification["paths"]

    for path in (
        "/auth/csrf",
        "/auth/login/password",
        "/auth/sms/send",
        "/auth/registration-ref",
        "/auth/register",
        "/auth/login/sms",
        "/auth/password/reset",
        "/auth/logout",
        "/me",
        "/me/profile",
        "/me/phone/code",
        "/me/phone",
        "/me/password",
        "/me/appearance",
        "/me/sessions/revoke",
    ):
        assert path in paths


def test_openapi_documents_session_csrf_and_minimum_user_data():
    specification = load_openapi()
    components = specification["components"]

    assert components["securitySchemes"]["cookieAuth"] == {
        "type": "apiKey",
        "in": "cookie",
        "name": "xianwen_session",
    }
    assert components["parameters"]["CsrfToken"]["name"] == "X-CSRFToken"
    assert components["parameters"]["CsrfToken"]["required"] is True
    assert set(components["schemas"]["User"]["properties"]) == {
        "id",
        "phone_masked",
        "nickname",
        "account_status",
        "commercial_identity",
        "home_route",
        "tenant",
        "appearance",
    }
    assert set(components["schemas"]["User"]["required"]) == {
        "id",
        "phone_masked",
        "nickname",
        "account_status",
        "commercial_identity",
        "home_route",
        "tenant",
        "appearance",
    }


def test_openapi_documents_sms_send_contract():
    specification = load_openapi()
    operation = specification["paths"]["/auth/sms/send"]["post"]
    schemas = specification["components"]["schemas"]

    assert operation["security"] == []
    assert operation["parameters"] == [{"$ref": "#/components/parameters/CsrfToken"}]
    assert set(operation["responses"]) == {"200", "403", "422", "429", "503"}
    assert schemas["SmsPurpose"]["enum"] == ["register", "login", "password_reset"]
    assert set(schemas["SmsSendEnvelope"]["allOf"][1]["properties"]["data"]["properties"]) == {
        "sent",
        "expires_in",
        "resend_after",
    }


def test_openapi_documents_registration_sms_login_and_password_reset():
    specification = load_openapi()
    paths = specification["paths"]
    schemas = specification["components"]["schemas"]
    error_codes = set(schemas["ErrorCode"]["enum"])

    expected_responses = {
        "/auth/register": {"201", "403", "409", "422", "429", "500", "503"},
        "/auth/login/sms": {"200", "401", "403", "422", "429", "500", "503"},
        "/auth/password/reset": {"200", "403", "422", "429", "500", "503"},
    }
    for path, responses in expected_responses.items():
        operation = paths[path]["post"]
        assert operation["security"] == []
        assert operation["parameters"] == [{"$ref": "#/components/parameters/CsrfToken"}]
        assert set(operation["responses"]) == responses

    assert set(schemas["RegistrationRequest"]["required"]) == {
        "phone",
        "nickname",
        "sms_code",
        "password",
    }
    assert "ref" in schemas["RegistrationRequest"]["properties"]
    assert set(schemas["SmsLoginRequest"]["required"]) == {"phone", "sms_code"}
    assert set(schemas["PasswordResetRequest"]["required"]) == {
        "phone",
        "sms_code",
        "new_password",
    }
    assert {
        "ACCOUNT_ALREADY_EXISTS",
        "AUTH_CREDENTIALS_INVALID",
        "ACCOUNT_UNAVAILABLE",
        "VERIFICATION_CODE_INVALID",
    } <= error_codes


def test_openapi_documents_account_settings_contract():
    specification = load_openapi()
    paths = specification["paths"]
    schemas = specification["components"]["schemas"]

    assert schemas["UserAppearance"]["properties"]["mode"]["enum"] == [
        "light",
        "dark",
        "system",
    ]
    assert schemas["UserAppearance"]["properties"]["accent"]["enum"] == [
        "blue",
        "green",
        "purple",
        "orange",
    ]
    assert set(schemas["PhoneCodeSendRequest"]["required"]) == {
        "phone",
        "current_password",
    }
    assert set(schemas["PhoneChangeRequest"]["required"]) == {
        "phone",
        "current_password",
        "code",
    }
    assert set(schemas["PasswordChangeRequest"]["required"]) == {
        "current_password",
        "new_password",
    }
    assert set(schemas["AppearanceUpdateRequest"]["required"]) == {"mode", "accent"}
    assert set(schemas["SessionRevokeRequest"]["required"]) == {"current_password"}

    for path, method in {
        "/me/profile": "patch",
        "/me/phone/code": "post",
        "/me/phone": "patch",
        "/me/password": "patch",
        "/me/appearance": "patch",
        "/me/sessions/revoke": "post",
    }.items():
        assert paths[path][method]["parameters"] == [
            {"$ref": "#/components/parameters/CsrfToken"}
        ]

    error_codes = set(schemas["ErrorCode"]["enum"])
    assert {
        "CURRENT_PASSWORD_INVALID",
        "PHONE_ALREADY_IN_USE",
        "PHONE_CHANGE_TARGET_INVALID",
    } <= error_codes
