from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = yaml.safe_load((ROOT / "openapi" / "openapi-v1.yaml").read_text(encoding="utf-8"))


def test_retired_workflow_paths_and_schemas_are_absent():
    paths = SPEC["paths"]
    schemas = SPEC["components"]["schemas"]

    assert not any(path.startswith("/admin/approvals") for path in paths)
    assert not any(name.startswith("ApprovalCreated") for name in schemas)
    assert "ApprovalRequest" not in schemas
    assert SPEC["components"]["schemas"]["RiskMode"]["enum"] == ["confirm", "password"]


def test_direct_risk_and_operation_record_paths_remain_documented():
    paths = SPEC["paths"]
    expected = {
        "/admin/admins/{adminId}/role",
        "/admin/roles/{roleId}/permissions",
        "/admin/risk-actions",
        "/admin/risk-policies",
        "/admin/risk-policies/{actionKey}",
        "/admin/audit-events",
        "/admin/audit-events/{eventId}",
    }
    assert expected <= paths.keys()
    operation = paths["/admin/risk-policies/{actionKey}"]["patch"]
    assert any(parameter["$ref"].endswith("/CsrfToken") for parameter in operation["parameters"])


def test_operation_record_schema_is_safe_and_hides_retired_workflow_fields():
    schemas = SPEC["components"]["schemas"]
    fields = set(schemas["AuditEvent"]["properties"])
    assert {"approver_id", "approval_request_id"}.isdisjoint(fields)
    assert {
        "payload",
        "sanitized_payload",
        "password",
        "phone",
        "ip",
        "exception",
    }.isdisjoint(fields)
    assert schemas["RiskPolicyUpdateRequest"]["properties"]["current_password"]["writeOnly"]


def test_composite_update_schemas_do_not_retain_high_risk_fields():
    schemas = SPEC["components"]["schemas"]
    assert "role_id" not in schemas["AdminUpdateRequest"]["properties"]
    assert "permission_keys" not in schemas["RoleUpdateRequest"]["properties"]
    assert "role_id" in schemas["AdminRoleChangeRiskRequest"]["allOf"][1]["properties"]
    assert "permission_keys" in schemas["RolePermissionsRiskRequest"]["allOf"][1]["properties"]


def test_retirement_and_data_preservation_are_documented():
    documentation = (ROOT / "docs" / "21-HIGH-RISK-ACTION-AUDIT.md").read_text(encoding="utf-8")
    for statement in (
        "不存在待处理队列、第二管理员决定或等待批准状态",
        "确认后直接执行",
        "当前数据库结构不再包含审批队列表或审批外键",
        "待处理记录在迁移时统一取消",
        "操作完成后写入 AuditEvent",
    ):
        assert statement in documentation
