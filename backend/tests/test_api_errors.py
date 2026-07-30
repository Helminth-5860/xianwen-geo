import json
from uuid import UUID

from django.test import RequestFactory
from rest_framework.test import APIClient

from apps.core.exceptions import csrf_failure


def assert_error(response, *, status_code: int, code: str):
    payload = response.json()
    assert response.status_code == status_code
    assert payload["success"] is False
    assert payload["error"]["code"] == code
    assert isinstance(payload["error"]["details"], dict)
    assert payload["request_id"] == response["X-Request-ID"]
    assert str(UUID(payload["request_id"])) == payload["request_id"]
    return payload


def test_validation_error_is_normalized(db):
    response = APIClient().post("/api/v1/test/validation/", data={}, format="json")

    payload = assert_error(response, status_code=422, code="VALIDATION_ERROR")
    field_error = payload["error"]["details"]["fields"]["name"][0]
    assert field_error == {"message": "该字段是必填项。", "code": "required"}


def test_auth_required_mapping(db):
    response = APIClient().get("/api/v1/test/protected/")
    assert_error(response, status_code=401, code="AUTH_REQUIRED")


def test_permission_denied_mapping(db):
    response = APIClient().get("/api/v1/test/forbidden/")
    assert_error(response, status_code=403, code="PERMISSION_DENIED")


def test_drf_not_found_mapping(db):
    response = APIClient().get("/api/v1/test/missing/")
    assert_error(response, status_code=404, code="RESOURCE_NOT_FOUND")


def test_url_not_found_mapping(db):
    response = APIClient().get("/api/v1/not-a-real-route/")
    assert_error(response, status_code=404, code="RESOURCE_NOT_FOUND")


def test_method_not_allowed_mapping(db):
    response = APIClient().post("/api/v1/test/get-only/", data={}, format="json")
    assert_error(response, status_code=405, code="METHOD_NOT_ALLOWED")


def test_invalid_json_mapping(db):
    response = APIClient().post(
        "/api/v1/test/parse/",
        data="{",
        content_type="application/json",
    )
    assert_error(response, status_code=400, code="INVALID_JSON")


def test_rate_limit_mapping(db):
    response = APIClient().get("/api/v1/test/throttled/")
    payload = assert_error(response, status_code=429, code="RATE_LIMITED")
    assert payload["error"]["details"] == {"retry_after": 3}


def test_internal_error_is_generic_and_does_not_leak(db):
    client = APIClient()
    client.raise_request_exception = False

    response = client.get("/api/v1/test/exception/")

    payload = assert_error(response, status_code=500, code="INTERNAL_ERROR")
    assert payload["error"] == {
        "code": "INTERNAL_ERROR",
        "message": "服务器内部错误",
        "details": {},
    }
    response_text = response.content.decode()
    assert "sensitive SQL password" not in response_text
    assert "secret.py" not in response_text
    assert "Traceback" not in response_text


def test_csrf_failure_uses_standard_error_envelope():
    request = RequestFactory().post("/api/v1/test/protected/")
    request.request_id = "a629a800-13cb-4e70-b4db-434231f27700"

    response = csrf_failure(request)
    payload = json.loads(response.content)

    assert response.status_code == 403
    assert payload["error"]["code"] == "CSRF_FAILED"
    assert payload["request_id"] == request.request_id
