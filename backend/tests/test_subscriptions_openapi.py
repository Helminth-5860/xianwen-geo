from pathlib import Path

import yaml

SPEC_PATH = Path(__file__).resolve().parents[2] / "openapi" / "openapi-v1.yaml"


def load_spec():
    return yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))


def test_subscription_paths_and_direct_confirmation_responses_are_documented():
    paths = load_spec()["paths"]
    read_paths = {"/subscription", "/admin/subscriptions", "/admin/subscriptions/{subscriptionId}"}
    write_paths = {
        "/admin/plan-applications/{applicationId}/activate",
        "/admin/users/{userId}/subscriptions/trial",
        "/admin/subscriptions/{subscriptionId}/terminate",
    }
    assert read_paths | write_paths <= paths.keys()
    assert "post" not in paths["/admin/subscriptions"]
    for path in write_paths:
        operation = paths[path]["post"]
        assert "200" in operation["responses"]
        assert "202" not in operation["responses"]
        assert {"401", "403", "404", "409", "422", "429", "503"} <= operation["responses"].keys()
        assert any(
            parameter.get("$ref") == "#/components/parameters/CsrfToken"
            for parameter in operation["parameters"]
        )


def test_subscription_schema_exposes_only_frozen_statuses_and_safe_user_fields():
    schemas = load_spec()["components"]["schemas"]
    assert schemas["SubscriptionStatus"]["enum"] == ["active", "expired", "terminated"]
    properties = schemas["Subscription"]["properties"]
    assert {
        "id",
        "plan_name",
        "plan_version_no",
        "status",
        "is_trial",
        "starts_at",
        "ends_at",
        "entitlement_summary",
    } <= properties.keys()
    assert {"entitlement_snapshot", "entitlement_digest", "opening_note"}.isdisjoint(properties)
    assert properties["cycle_anchor_time"] == {"type": "string", "format": "time"}
    assert schemas["SubscriptionChangeStatus"]["enum"] == [
        "scheduled",
        "executed",
        "cancelled",
        "failed",
    ]


def test_trial_and_open_requests_do_not_accept_server_owned_flags():
    schemas = load_spec()["components"]["schemas"]
    trial = schemas["GrantTrialRequest"]["properties"]
    assert set(trial) <= {"expected_version", "plan_id", "opening_note", "confirmed"}
    assert {"is_trial", "plan_version_id"}.isdisjoint(trial)
    open_request = schemas["OpenSubscriptionRequest"]["properties"]
    assert "selected_plan_version_id" in open_request
    assert "confirmed" in open_request
    assert "current_password" not in open_request
