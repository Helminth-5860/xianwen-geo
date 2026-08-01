from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = yaml.safe_load((ROOT / "openapi" / "openapi-v1.yaml").read_text(encoding="utf-8"))


def test_xw0107_paths_are_complete_and_generic_approval_create_is_absent():
    paths = SPEC["paths"]
    expected = {
        "/admin/admins/{adminId}/role",
        "/admin/roles/{roleId}/permissions",
        "/admin/risk-actions",
        "/admin/risk-policies",
        "/admin/risk-policies/{actionKey}",
        "/admin/approvals",
        "/admin/approvals/{approvalId}",
        "/admin/approvals/{approvalId}/approve",
        "/admin/approvals/{approvalId}/reject",
        "/admin/approvals/{approvalId}/cancel",
        "/admin/audit-events",
        "/admin/audit-events/{eventId}",
    }
    assert expected <= paths.keys()
    assert set(paths["/admin/approvals"]) == {"get"}
    for path in (
        "/admin/risk-policies/{actionKey}",
        "/admin/approvals/{approvalId}/approve",
        "/admin/approvals/{approvalId}/reject",
        "/admin/approvals/{approvalId}/cancel",
    ):
        operation = paths[path]["patch" if "risk-policies" in path else "post"]
        assert any(
            parameter["$ref"].endswith("/CsrfToken") for parameter in operation["parameters"]
        )


def test_xw0107_schemas_document_safe_payload_and_terminal_states():
    schemas = SPEC["components"]["schemas"]
    assert schemas["ApprovalRequestStatus"]["enum"] == [
        "pending",
        "rejected",
        "cancelled",
        "expired",
        "stale",
        "executed",
        "execution_failed",
    ]
    approval_properties = schemas["ApprovalRequest"]["properties"]
    assert "sanitized_payload" not in approval_properties
    assert "payload_digest" not in approval_properties
    serialized = str(
        {
            key: schemas[key]
            for key in (
                "ApprovalRequest",
                "ApprovalCreated",
                "AuditEvent",
                "RiskPolicyUpdateRequest",
            )
        }
    ).lower()
    for forbidden in (
        "sms_code",
        "authorization",
        "cookie",
        "challenge",
        "database_url",
        "redis_url",
        "phone",
    ):
        assert forbidden not in serialized
    assert schemas["RiskPolicyUpdateRequest"]["properties"]["current_password"]["writeOnly"]


def test_xw0107_composite_update_schemas_do_not_retain_high_risk_fields():
    schemas = SPEC["components"]["schemas"]
    assert "role_id" not in schemas["AdminUpdateRequest"]["properties"]
    assert "permission_keys" not in schemas["RoleUpdateRequest"]["properties"]
    assert "role_id" in schemas["AdminRoleChangeRiskRequest"]["allOf"][1]["properties"]
    assert "permission_keys" in schemas["RolePermissionsRiskRequest"]["allOf"][1]["properties"]


def test_xw0107_rollback_and_audit_limitations_are_documented():
    documentation = (ROOT / "docs" / "21-HIGH-RISK-APPROVAL-AUDIT.md").read_text(encoding="utf-8")
    migration = (
        ROOT / "backend" / "apps" / "admin_rbac" / "migrations" / "0007_seed_risk_catalog.py"
    ).read_text(encoding="utf-8")
    assert "RunPython.noop" in migration
    for statement in (
        "单独回退 Seed 不删除目录、默认策略或权限",
        "完整回退建表迁移会删除审批和统一审计表及证据",
        "任何逆向迁移前必须完成影响审查和可恢复备份",
        "不实现全局 hash chain、外部 WORM 或 SIEM",
        "未连接腾讯云 PostgreSQL、Redis 或短信服务",
    ):
        assert statement in documentation
