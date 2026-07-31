from pathlib import Path

from yaml import safe_load


def load_openapi():
    path = Path(__file__).resolve().parents[2] / "openapi" / "openapi-v1.yaml"
    return safe_load(path.read_text(encoding="utf-8"))


def test_xw0104_paths_and_csrf_contracts_are_documented():
    specification = load_openapi()
    paths = specification["paths"]
    expected_paths = {
        "/me/approval/resubmit",
        "/notifications",
        "/notifications/{notificationId}/read",
        "/admin/users",
        "/admin/users/{userId}",
        "/admin/users/{userId}/history",
        "/admin/users/{userId}/review",
        "/admin/users/{userId}/freeze",
        "/admin/users/{userId}/unfreeze",
    }
    assert expected_paths <= set(paths)

    csrf_ref = {"$ref": "#/components/parameters/CsrfToken"}
    for path in (
        "/me/approval/resubmit",
        "/notifications/{notificationId}/read",
        "/admin/users/{userId}/review",
        "/admin/users/{userId}/freeze",
        "/admin/users/{userId}/unfreeze",
    ):
        assert csrf_ref in paths[path]["post"]["parameters"]


def test_xw0104_schemas_minimize_phone_and_notification_content():
    schemas = load_openapi()["components"]["schemas"]
    admin_properties = schemas["AdminUser"]["properties"]
    notification_properties = schemas["Notification"]["properties"]

    assert "phone_masked" in admin_properties
    assert "phone" not in admin_properties
    assert "session_version" not in admin_properties
    assert "safe_summary" in notification_properties
    assert "reason" not in notification_properties
    assert schemas["Pagination"]["properties"]["page_size"]["maximum"] == 100


def test_xw0104_state_and_error_enums_are_stable():
    schemas = load_openapi()["components"]["schemas"]
    assert schemas["ApprovalStatus"]["enum"] == ["pending", "approved", "rejected"]
    assert schemas["AccountStatus"]["enum"] == [
        "active",
        "frozen",
        "cancel_pending",
        "cancelled",
    ]
    assert schemas["UserStatusEvent"]["properties"]["status_domain"]["enum"] == [
        "approval",
        "account",
    ]
    assert {
        "APPROVAL_STATE_CONFLICT",
        "ACCOUNT_STATE_CONFLICT",
        "APPROVAL_REASON_REQUIRED",
        "ACCOUNT_UNAVAILABLE",
        "PERMISSION_DENIED",
        "RESOURCE_NOT_FOUND",
    } <= set(schemas["ErrorCode"]["enum"])


def test_history_exposes_no_mutating_operation():
    path = load_openapi()["paths"]["/admin/users/{userId}/history"]
    assert set(path) == {"parameters", "get"}
