from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = yaml.safe_load((ROOT / "openapi" / "openapi-v1.yaml").read_text(encoding="utf-8"))


OPERATIONS = {
    ("/admin/risk-actions", "get"): {"200", "401", "403"},
    ("/admin/risk-policies", "get"): {"200", "401", "403"},
    (
        "/admin/risk-policies/{actionKey}",
        "patch",
    ): {"200", "401", "403", "404", "409", "422", "429", "503"},
    ("/admin/audit-events", "get"): {"200", "401", "403"},
    (
        "/admin/audit-events/{eventId}",
        "get",
    ): {"200", "401", "403", "404"},
}


def test_every_high_risk_operation_declares_auth_and_real_response_matrix():
    for (path, method), expected in OPERATIONS.items():
        responses = set(SPEC["paths"][path][method]["responses"])
        assert expected <= responses, (path, method, expected - responses)


def test_retired_workflow_is_absent_and_audit_schema_never_exposes_payload():
    schemas = SPEC["components"]["schemas"]
    assert not any(path.startswith("/admin/approvals") for path in SPEC["paths"])
    assert "ApprovalRequest" not in schemas
    audit_fields = set(schemas["AuditEvent"]["properties"])
    assert (
        not {
            "payload",
            "sanitized_payload",
            "password",
            "phone",
            "ip",
            "exception",
        }
        & audit_fields
    )
    assert {"approver_id", "approval_request_id"}.isdisjoint(audit_fields)


def test_password_and_composite_patch_contracts_match_runtime_security_boundary():
    schemas = SPEC["components"]["schemas"]
    assert schemas["RiskPolicyUpdateRequest"]["properties"]["current_password"]["writeOnly"]
    assert "data_scope" not in schemas["RoleUpdateRequest"]["properties"]
    assert not {
        "role_id",
        "admin_status",
        "is_staff",
        "is_superuser",
        "security",
    } & set(schemas["AdminUpdateRequest"]["properties"])
    assert not {
        "permission_keys",
        "data_scope",
        "status",
        "security",
        "ip_allowlist",
    } & set(schemas["RoleUpdateRequest"]["properties"])


def test_customer_assignment_read_and_risk_mutation_are_documented():
    path = SPEC["paths"]["/admin/users/{userId}/assignment"]
    assert {"get", "put"} <= path.keys()
    assert {"200", "401", "403", "404"} <= set(path["get"]["responses"])
    assert {
        "200",
        "401",
        "403",
        "404",
        "409",
        "422",
        "429",
        "503",
    } <= set(path["put"]["responses"])
    properties = SPEC["components"]["schemas"]["AssignmentUpdateRequest"]["properties"]
    assert properties["current_password"]["writeOnly"]
    assert properties["owner_admin_id"]["nullable"] is True
    assert {"owner_admin_id", "expected_version", "reason", "confirmed"} <= properties.keys()
