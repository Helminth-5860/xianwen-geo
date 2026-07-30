from unittest.mock import patch

from django.db import OperationalError
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient


def test_health_check_reports_dependencies_available(db):
    response = APIClient().get(reverse("core:health"))

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "status": "ok",
        "service": "xianwen-geo-api",
        "checks": {"database": True, "redis": True},
    }


def test_health_check_returns_503_without_leaking_exception(db):
    with patch(
        "apps.core.views.connection.ensure_connection",
        side_effect=OperationalError("sensitive database detail"),
    ):
        response = APIClient().get(reverse("core:health"))

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.json()["status"] == "unavailable"
    assert "sensitive database detail" not in response.content.decode()
