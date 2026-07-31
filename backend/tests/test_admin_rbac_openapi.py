from pathlib import Path

import yaml

SPEC = yaml.safe_load(
    (Path(__file__).resolve().parents[2] / "openapi" / "openapi-v1.yaml").read_text(
        encoding="utf-8"
    )
)


def test_xw0105_paths_are_documented():
    paths = SPEC["paths"]
    expected = {
        "/admin/me",
        "/admin/admins",
        "/admin/admins/{adminId}",
        "/admin/admins/{adminId}/disable",
        "/admin/admins/{adminId}/enable",
        "/admin/admins/{adminId}/lock",
        "/admin/admins/{adminId}/unlock",
        "/admin/roles",
        "/admin/roles/{roleId}",
        "/admin/roles/{roleId}/disable",
        "/admin/permissions",
        "/admin/users/{userId}/assignment",
    }
    assert expected <= paths.keys()


def test_xw0105_write_operations_document_csrf_and_versions():
    paths = SPEC["paths"]
    assert paths["/admin/admins/{adminId}"]["patch"]["requestBody"]
    assert paths["/admin/roles/{roleId}"]["patch"]["requestBody"]
    assignment = paths["/admin/users/{userId}/assignment"]["put"]
    assert any(item["$ref"].endswith("/CsrfToken") for item in assignment["parameters"])
    schemas = SPEC["components"]["schemas"]
    assert "expected_version" in schemas["AdminUpdateRequest"]["required"]
    assert schemas["AssignmentUpdateRequest"]["properties"]["expected_version"]["minimum"] == 0


def test_admin_schemas_do_not_expose_credentials_or_full_phone():
    serialized = str(
        {
            key: SPEC["components"]["schemas"][key]
            for key in ("AdminProfile", "AdminContextEnvelope")
        }
    )
    for forbidden in ("password", "session", "cookie", "phone_hash"):
        assert forbidden not in serialized.lower()
    assert "phone_masked" in serialized


def test_xw0105_documents_irreversible_seed_migration_boundary():
    repo_root = Path(__file__).resolve().parents[2]
    documentation = (repo_root / "docs" / "19-ADMIN-RBAC-DATA-SCOPE.md").read_text(encoding="utf-8")
    migration = (
        repo_root
        / "backend"
        / "apps"
        / "admin_rbac"
        / "migrations"
        / "0002_seed_catalog_and_profiles.py"
    ).read_text(encoding="utf-8")

    assert "RunPython.noop" in migration
    for required_statement in (
        "单独回退 0002 不恢复",
        "单独回退 0002 不删除 Permission Seed 或 AdminProfile",
        "完整回退 0001 会删除全部 RBAC 表",
        "前向修复或从经过验证的备份恢复",
        "任何逆向迁移前必须审查影响并完成可恢复备份",
        "未连接腾讯云 PostgreSQL",
    ):
        assert required_statement in documentation
