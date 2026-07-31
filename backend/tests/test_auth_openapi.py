from pathlib import Path

from yaml import safe_load


def load_openapi():
    path = Path(__file__).resolve().parents[2] / "openapi" / "openapi-v1.yaml"
    return safe_load(path.read_text(encoding="utf-8"))


def test_openapi_exposes_only_implemented_xw_0101_auth_endpoints():
    specification = load_openapi()
    paths = specification["paths"]

    for path in (
        "/auth/csrf",
        "/auth/login/password",
        "/auth/logout",
        "/me",
    ):
        assert path in paths
    for unavailable_path in (
        "/auth/register",
        "/auth/login/sms",
        "/auth/password/reset",
        "/auth/sms/send",
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
