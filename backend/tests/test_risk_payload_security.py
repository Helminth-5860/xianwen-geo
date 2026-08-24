import uuid

import pytest

from apps.admin_rbac.models import AuditEvent
from apps.admin_rbac.risk_services import (
    MAX_RISK_PAYLOAD_BYTES,
    RiskPayloadInvalid,
    canonical_payload,
)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "field",
    [
        "password",
        "current_password",
        "sms_code",
        "cookie",
        "cookies",
        "session",
        "session_id",
        "challenge",
        "challenge_id",
        "api_key",
        "secret",
        "private_key",
        "access_token",
        "refresh_token",
        "sql",
        "command",
        "url",
        "callback_url",
        "import_path",
        "callable",
    ],
)
def test_sensitive_payload_fields_are_explicitly_rejected(field):
    with pytest.raises(RiskPayloadInvalid) as captured:
        canonical_payload("user.freeze", "user", uuid.uuid4(), 1, {field: "do-not-store"})
    assert captured.value.code == "RISK_PAYLOAD_INVALID"
    assert not AuditEvent.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        {"reason": "x" * MAX_RISK_PAYLOAD_BYTES},
        {"reason": "safe\u0000unsafe"},
        {"reason": "<script>alert(1)</script>"},
        {"operation": "create", "sql": "select secret"},
        {"nested": {"alias": {"Current-Password": "do-not-store"}}},
    ],
)
def test_payload_size_control_html_mixed_operation_and_nested_aliases_are_rejected(
    payload,
):
    with pytest.raises(RiskPayloadInvalid):
        canonical_payload("user.freeze", "user", uuid.uuid4(), 1, payload)


def test_payload_invalid_maps_to_stable_422_envelope_without_echoing_value():
    from rest_framework.test import APIRequestFactory

    from apps.admin_rbac.risk_views import risk_error_response

    request = APIRequestFactory().post("/api/v1/admin/users/target/freeze")
    request.request_id = str(uuid.uuid4())
    response = risk_error_response(RiskPayloadInvalid(), request)

    assert response.status_code == 422
    assert response.data["success"] is False
    assert response.data["error"] == {
        "code": "RISK_PAYLOAD_INVALID",
        "message": response.data["error"]["message"],
        "details": {},
    }
    assert response.data["request_id"] == request.request_id
    assert "do-not-store" not in repr(response.data)
