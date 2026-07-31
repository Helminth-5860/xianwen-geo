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
        "/auth/logout",
        "/me",
    ):
        assert path in paths
    for unavailable_path in (
        "/auth/register",
        "/auth/login/sms",
        "/auth/password/reset",
    ):
        assert unavailable_path not in paths


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
    }
    assert set(components["schemas"]["User"]["required"]) == {
        "id",
        "phone_masked",
        "nickname",
        "approval_status",
        "account_status",
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
