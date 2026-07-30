from unittest.mock import patch
from uuid import UUID

from django.db import OperationalError
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient


def test_health_check_reports_standard_success_envelope(db):
    response = APIClient().get(reverse("core:health"))

    request_id = response["X-Request-ID"]
    assert str(UUID(request_id)) == request_id
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "success": True,
        "data": {"status": "ok"},
        "request_id": request_id,
    }


def test_health_check_returns_standard_503_without_leaking_exception(db):
    with patch(
        "apps.core.views.connection.ensure_connection",
        side_effect=OperationalError("sensitive database detail"),
    ):
        response = APIClient().get(reverse("core:health"))

    payload = response.json()
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert payload["success"] is False
    assert payload["error"]["code"] == "SERVICE_TEMPORARILY_UNAVAILABLE"
    assert payload["request_id"] == response["X-Request-ID"]
    assert "sensitive database detail" not in response.content.decode()
