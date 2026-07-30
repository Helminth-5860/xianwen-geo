import logging
from uuid import UUID, uuid4

import pytest
from rest_framework.test import APIClient

from apps.core.context import get_request_id


def assert_uuid(value: str) -> None:
    assert str(UUID(value)) == value.lower()


def test_missing_request_id_is_generated(db):
    response = APIClient().get("/api/v1/health/")

    header_request_id = response["X-Request-ID"]
    assert_uuid(header_request_id)
    assert response.json()["request_id"] == header_request_id


def test_valid_request_id_crosses_header_body_and_request_log(db, caplog):
    request_id = str(uuid4())
    caplog.set_level(logging.INFO, logger="xianwen.request")

    response = APIClient().get("/api/v1/health/", HTTP_X_REQUEST_ID=request_id)

    assert response["X-Request-ID"] == request_id
    assert response.json()["request_id"] == request_id
    request_logs = [record for record in caplog.records if record.name == "xianwen.request"]
    assert request_logs
    request_log = request_logs[-1]
    assert request_log.request_id == request_id
    assert request_log.method == "GET"
    assert request_log.path == "/api/v1/health/"
    assert request_log.status_code == 200
    assert request_log.duration_ms >= 0


@pytest.mark.parametrize(
    "invalid_request_id",
    ["not-a-uuid", "x" * 100, "not-a-uuid\nwith-control-character"],
)
def test_invalid_request_id_is_replaced(db, invalid_request_id):
    response = APIClient().get(
        "/api/v1/health/",
        HTTP_X_REQUEST_ID=invalid_request_id,
    )

    replacement = response["X-Request-ID"]
    assert replacement != invalid_request_id
    assert_uuid(replacement)
    assert response.json()["request_id"] == replacement


def test_consecutive_requests_do_not_share_context(db):
    first = APIClient().get("/api/v1/health/")
    assert get_request_id() is None
    second = APIClient().get("/api/v1/health/")

    assert first["X-Request-ID"] != second["X-Request-ID"]
    assert get_request_id() is None
