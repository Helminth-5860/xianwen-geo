from pathlib import Path

import yaml

SPEC_PATH = Path(__file__).resolve().parents[2] / "openapi" / "openapi-v1.yaml"


def test_question_catalog_openapi_exposes_only_frozen_catalog_operations():
    spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    paths = spec["paths"]
    expected_methods = {
        "/question-categories": {"get"},
        "/admin/question-categories": {"get", "post"},
        "/admin/question-categories/{categoryId}": {"get", "patch", "parameters"},
        "/admin/question-categories/{categoryId}/enable": {"post", "parameters"},
        "/admin/question-categories/{categoryId}/disable": {"post", "parameters"},
        "/admin/question-tags": {"get", "post"},
        "/admin/question-tags/{tagId}": {"get", "patch", "parameters"},
        "/admin/question-tags/{tagId}/enable": {"post", "parameters"},
        "/admin/question-tags/{tagId}/disable": {"post", "parameters"},
    }
    for path, methods in expected_methods.items():
        assert path in paths
        assert set(paths[path]) == methods
        assert "delete" not in paths[path]


def test_question_catalog_openapi_requires_versions_and_declares_no_delete():
    spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    schemas = spec["components"]["schemas"]
    for schema_name in ("QuestionCategoryUpdateRequest", "QuestionTagUpdateRequest"):
        schema = schemas[schema_name]
        assert schema["additionalProperties"] is False
        assert "expected_version" in schema["required"]
        assert "key" not in schema["properties"]
    assert schemas["ExpectedQuestionCatalogVersion"]["required"] == ["expected_version"]
    assert schemas["AdminQuestionCategory"]["properties"]["can_delete"]["const"] is False
    assert schemas["AdminQuestionTag"]["properties"]["can_delete"]["const"] is False
