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
