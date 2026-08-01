from pathlib import Path

import yaml

SPEC_PATH = Path(__file__).resolve().parents[2] / "openapi" / "openapi-v1.yaml"


def load_spec():
    return yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))


def test_plan_application_paths_are_canonical_and_have_no_activation_or_delete():
    paths = load_spec()["paths"]
    required = {
        "/plan-applications",
        "/plan-applications/{applicationId}",
        "/plan-applications/{applicationId}/cancel",
        "/admin/plan-applications",
        "/admin/plan-applications/{applicationId}",
        "/admin/plan-applications/{applicationId}/contact",
        "/admin/plan-applications/{applicationId}/close",
    }
    assert required <= paths.keys()
    assert not any("package-applications" in path or "activate" in path for path in paths)
    assert all("delete" not in paths[path] for path in required)


def test_plan_application_create_documents_idempotency_and_replay_status():
    operation = load_spec()["paths"]["/plan-applications"]["post"]
    parameters = {item.get("$ref", "") for item in operation["parameters"]}
    assert "#/components/parameters/IdempotencyKey" in parameters
    assert {"200", "201", "401", "403", "409", "422", "429", "503"} <= operation["responses"].keys()


def test_plan_application_status_and_sensitive_field_schemas_are_frozen():
    schemas = load_spec()["components"]["schemas"]
    assert schemas["PlanApplicationStatus"]["enum"] == [
        "pending",
        "contacted",
        "closed",
        "cancelled",
    ]
    user_properties = schemas["PlanApplication"]["properties"]
    admin_detail = schemas["AdminPlanApplicationDetail"]["allOf"][1]["properties"]
    assert "applicant_phone" not in user_properties
    assert admin_detail["applicant_phone"]["description"].startswith("仅详情")
    action = schemas["PlanApplicationAdminActionRequest"]["allOf"][1]["properties"]
    assert action["current_password"]["writeOnly"] is True


def test_public_plan_exposes_current_version_for_server_verified_application():
    schema = load_spec()["components"]["schemas"]["PublicPlan"]
    assert {"plan_version_id", "version_no"} <= set(schema["required"])
    assert schema["properties"]["plan_version_id"]["readOnly"] is True
