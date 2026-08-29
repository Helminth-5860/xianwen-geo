from pathlib import Path

import yaml

SPEC_PATH = Path(__file__).resolve().parents[2] / "openapi" / "openapi-v1.yaml"


def _spec():
    return yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))


def test_competitor_management_and_comparison_paths_are_documented():
    paths = _spec()["paths"]
    assert {"get", "post"} <= paths["/subjects/{subjectId}/competitors"].keys()
    assert {"patch", "delete"} <= paths["/subjects/{subjectId}/competitors/{competitorId}"].keys()
    assert "get" in paths["/subjects/{subjectId}/competitors/comparison"]


def test_competitor_writes_require_csrf_and_strict_payloads():
    spec = _spec()
    paths = spec["paths"]
    for path, method in (
        ("/subjects/{subjectId}/competitors", "post"),
        ("/subjects/{subjectId}/competitors/{competitorId}", "patch"),
        ("/subjects/{subjectId}/competitors/{competitorId}", "delete"),
    ):
        refs = {item.get("$ref") for item in paths[path][method]["parameters"]}
        assert "#/components/parameters/CsrfToken" in refs

    schemas = spec["components"]["schemas"]
    assert schemas["SubjectCompetitorCreateRequest"]["additionalProperties"] is False
    assert schemas["SubjectCompetitorUpdateRequest"]["additionalProperties"] is False
    assert "expected_version" in schemas["SubjectCompetitorUpdateRequest"]["required"]
    assert schemas["SubjectCompetitorUpdateRequest"]["anyOf"] == [
        {"required": ["name"]},
        {"required": ["website"]},
    ]


def test_competitor_contract_has_real_metrics_and_registered_errors():
    schemas = _spec()["components"]["schemas"]
    comparison = schemas["CompetitorComparison"]
    assert comparison["properties"]["status"]["enum"] == [
        "no_competitors",
        "no_detection_data",
        "ready",
    ]
    assert {
        "mention_count",
        "mention_rate",
        "question_coverage_count",
        "question_coverage_rate",
        "shared_question_count",
        "gap_question_count",
        "recommendation_rate",
        "citation_count",
    } == set(schemas["CompetitorComparisonMetrics"]["properties"])
    assert {
        "COMPETITOR_VALUES_INVALID",
        "COMPETITOR_LIMIT_REACHED",
        "COMPETITOR_DUPLICATE",
        "COMPETITOR_IS_SUBJECT",
        "COMPETITOR_VERSION_CONFLICT",
        "COMPETITOR_NOT_FOUND",
    } <= set(schemas["ErrorCode"]["enum"])
