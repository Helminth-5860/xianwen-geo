from pathlib import Path

import yaml

SPEC_PATH = Path(__file__).resolve().parents[2] / "openapi" / "openapi-v1.yaml"


def load_spec():
    return yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))


def test_subject_catalog_paths_are_complete_without_delete_routes():
    paths = load_spec()["paths"]
    expected_methods = {
        "/subjects": {"get", "post"},
        "/subjects/{subjectId}": {"get"},
        "/subjects/{subjectId}/draft": {"patch"},
        "/subjects/{subjectId}/archive": {"post"},
        "/subjects/{subjectId}/activate": {"post"},
        "/subjects/{subjectId}/commit": {"post"},
        "/subjects/{subjectId}/versions": {"get"},
        "/subjects/{subjectId}/versions/{versionId}": {"get"},
        "/subjects/current": {"put"},
        "/subject-types": {"get"},
        "/subject-types/{subjectTypeId}/form-schema": {"get"},
        "/admin/subject-types": {"get", "post"},
        "/admin/subject-types/{subjectTypeId}": {"get", "patch"},
        "/admin/subject-types/{subjectTypeId}/enable": {"post"},
        "/admin/subject-types/{subjectTypeId}/disable": {"post"},
        "/admin/subject-types/{subjectTypeId}/fields": {"get", "post"},
        "/admin/subject-types/{subjectTypeId}/field-order": {"put"},
        "/admin/subject-type-fields/{configId}": {"patch"},
        "/admin/subject-type-fields/{configId}/options": {"post"},
        "/admin/subject-field-options/{optionId}": {"patch"},
    }
    for path, methods in expected_methods.items():
        assert path in paths
        assert methods <= paths[path].keys()
        assert "delete" not in paths[path]
    assert not any(
        ("upload" in path or "presign" in path)
        for path in paths
        if path.startswith("/admin/subject-")
    )


def test_subject_schema_writes_require_csrf_and_expected_versions():
    spec = load_spec()
    paths = spec["paths"]
    writes = (
        ("/admin/subject-types", "post"),
        ("/subjects", "post"),
        ("/subjects/{subjectId}/draft", "patch"),
        ("/subjects/{subjectId}/archive", "post"),
        ("/subjects/{subjectId}/activate", "post"),
        ("/subjects/{subjectId}/commit", "post"),
        ("/subjects/current", "put"),
        ("/admin/subject-types/{subjectTypeId}", "patch"),
        ("/admin/subject-types/{subjectTypeId}/enable", "post"),
        ("/admin/subject-types/{subjectTypeId}/disable", "post"),
        ("/admin/subject-types/{subjectTypeId}/fields", "post"),
        ("/admin/subject-types/{subjectTypeId}/field-order", "put"),
        ("/admin/subject-type-fields/{configId}", "patch"),
        ("/admin/subject-type-fields/{configId}/options", "post"),
        ("/admin/subject-field-options/{optionId}", "patch"),
    )
    for path, method in writes:
        refs = {item.get("$ref") for item in paths[path][method].get("parameters", [])}
        assert "#/components/parameters/CsrfToken" in refs

    schemas = spec["components"]["schemas"]
    versioned = (
        "SubjectTypeUpdateRequest",
        "ExpectedSubjectTypeVersions",
        "CustomSubjectFieldCreateRequest",
        "SubjectFieldConfigUpdateRequest",
        "SubjectFieldOptionCreateRequest",
        "SubjectFieldOptionUpdateRequest",
        "SubjectFieldOrderRequest",
    )
    for name in versioned:
        assert "expected_schema_version" in schemas[name]["required"]
        assert schemas[name]["additionalProperties"] is False
    assert "expected_version" in schemas["SubjectFieldConfigUpdateRequest"]["required"]
    assert "expected_version" in schemas["SubjectFieldOptionUpdateRequest"]["required"]
    assert "expected_config_version" in schemas["SubjectFieldOptionCreateRequest"]["required"]
    assert "expected_schema_version" in schemas["SubjectCreateRequest"]["required"]
    assert "expected_version" in schemas["SubjectDraftUpdateRequest"]["required"]
    assert "expected_version" in schemas["SubjectStatusRequest"]["required"]
    assert "expected_version" in schemas["SubjectCurrentRequest"]["required"]
    commit = schemas["SubjectCommitRequest"]
    assert commit["additionalProperties"] is False
    assert set(commit["required"]) == {"expected_version", "products"}
    assert set(commit["properties"]) == {"expected_version", "products"}


def test_subject_machine_semantics_and_public_schema_are_minimal():
    schemas = load_spec()["components"]["schemas"]
    assert schemas["SubjectFieldType"]["enum"] == [
        "text",
        "textarea",
        "number",
        "date",
        "single",
        "multi",
        "select",
        "url",
        "image",
        "file",
    ]
    update_properties = schemas["SubjectFieldConfigUpdateRequest"]["properties"]
    assert not {"field_key", "field_type", "scope", "owner_subject_type", "is_builtin"} & set(
        update_properties
    )
    option_update = schemas["SubjectFieldOptionUpdateRequest"]["properties"]
    assert "option_key" not in option_update

    public_config = schemas["PublicSubjectFieldConfig"]
    assert not {"version", "is_builtin", "enabled"} & set(public_config["properties"])
    public_option = schemas["PublicSubjectFieldOption"]
    assert not {"version", "enabled"} & set(public_option["properties"])


def test_subject_error_codes_are_registered_in_the_common_envelope():
    codes = set(load_spec()["components"]["schemas"]["ErrorCode"]["enum"])
    assert {
        "SUBJECT_TYPE_VERSION_CONFLICT",
        "SUBJECT_SCHEMA_VERSION_CONFLICT",
        "SUBJECT_TYPE_KEY_CONFLICT",
        "SUBJECT_FIELD_KEY_CONFLICT",
        "SUBJECT_FIELD_CONFIG_INVALID",
        "SUBJECT_TYPE_STATE_CONFLICT",
        "SUBJECT_SCHEMA_MISMATCH",
        "SUBJECT_FIELD_VALUES_INVALID",
        "SUBJECT_LIMIT_REACHED",
        "SUBJECT_LIMIT_RECONCILIATION_REQUIRED",
        "SUBJECT_ENTITLEMENT_INTEGRITY_ERROR",
        "SUBJECT_VERSION_CONFLICT",
        "SUBJECT_CURRENT_VERSION_CONFLICT",
        "SUBJECT_STATE_CONFLICT",
        "PLAN_REQUIRED",
        "SUBJECT_REQUIRED_FIELDS_INCOMPLETE",
        "SUBJECT_SEMANTICS_INVALID",
        "SUBJECT_PRODUCT_CONFIRMATION_INVALID",
        "SUBJECT_VERSION_NO_CHANGES",
    } <= codes


def test_subject_risk_catalog_review_and_minimal_exposure_contract():
    spec = load_spec()
    paths = spec["paths"]
    expected = {
        "/admin/subject-risk-types": {"get", "post"},
        "/admin/subject-risk-types/{riskTypeId}": {"patch"},
        "/admin/subject-risk-rules": {"get", "post"},
        "/admin/subject-risk-rules/{riskRuleId}": {"patch"},
        "/admin/subject-risk-catalog": {"get"},
        "/admin/subject-risk-catalog/publish": {"post"},
        "/admin/subject-reviews": {"get"},
        "/admin/subject-reviews/{reviewId}": {"get"},
        "/admin/subject-reviews/{reviewId}/approve": {"post"},
        "/admin/subject-reviews/{reviewId}/reject": {"post"},
    }
    for path, methods in expected.items():
        assert path in paths
        assert methods <= paths[path].keys()
        assert "delete" not in paths[path]

    writes = [
        (path, method)
        for path, methods in expected.items()
        for method in methods
        if method in {"post", "patch", "put"}
    ]
    for path, method in writes:
        refs = {item.get("$ref") for item in paths[path][method].get("parameters", [])}
        assert "#/components/parameters/CsrfToken" in refs

    schemas = spec["components"]["schemas"]
    assert schemas["SubjectRiskOperator"]["enum"] == ["equals_any", "contains_any"]
    assert set(schemas["SubjectRiskCatalogPublishRequest"]["required"]) == {
        "expected_catalog_version"
    }
    assert schemas["SubjectRiskCatalogPublishRequest"]["additionalProperties"] is False
    assert schemas["SubjectReviewDecisionRequest"]["additionalProperties"] is False
    review_properties = set(schemas["SubjectReview"]["properties"])
    assert (
        not {
            "field_values",
            "schema_snapshot",
            "semantic_digest",
            "catalog_snapshot",
            "matched_value",
        }
        & review_properties
    )
    detail_required = spec["components"]["schemas"]["SubjectDetail"]["allOf"][1]["required"]
    assert "risk" in detail_required
    assert "/admin/approvals" not in paths
