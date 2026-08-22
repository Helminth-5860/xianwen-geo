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
        "/auth/register",
        "/auth/login/sms",
        "/auth/password/reset",
        "/auth/logout",
        "/me",
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
        "approval_status",
        "account_status",
        "approval_reason",
        "commercial_identity",
        "home_route",
        "tenant",
    }
    assert set(components["schemas"]["User"]["required"]) == {
        "id",
        "phone_masked",
        "nickname",
        "approval_status",
        "account_status",
        "commercial_identity",
        "home_route",
        "tenant",
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
