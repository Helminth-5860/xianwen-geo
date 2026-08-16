from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = yaml.safe_load((ROOT / "openapi/openapi-v1.yaml").read_text(encoding="utf-8"))


def test_keyword_editor_and_generation_paths_exist():
    paths = SPEC["paths"]
    expected = {
        "/subjects/{subjectId}/keywords/draft",
        "/subjects/{subjectId}/keywords/current",
        "/subjects/{subjectId}/keywords/commit",
        "/subjects/{subjectId}/keywords/versions",
        "/subjects/{subjectId}/keywords/versions/{versionId}",
        "/subjects/{subjectId}/keywords/generate",
        "/keyword-jobs/{jobId}",
    }
    assert expected <= set(paths)
    assert "post" in paths["/subjects/{subjectId}/keywords/generate"]
    assert "get" in paths["/keyword-jobs/{jobId}"]


def test_keyword_write_contract_is_strict_and_does_not_accept_internal_fields():
    schemas = SPEC["components"]["schemas"]
    draft = schemas["KeywordDraftSaveRequest"]
    commit = schemas["KeywordCommitRequest"]
    assert draft["additionalProperties"] is False
    assert commit["additionalProperties"] is False
    assert {"expected_version", "expected_subject_version_id", "items"} <= set(draft["required"])
    assert {"expected_version", "expected_subject_version_id"} <= set(commit["required"])
    forbidden = {"matching_text", "region_matching_key", "content_digest", "current_version"}
    assert forbidden.isdisjoint(draft["properties"])
    item = schemas["KeywordItemInput"]["properties"]
    assert {
        "base_keyword_text",
        "business_category",
        "search_intent",
        "relevance_score",
        "priority",
        "ai_reason",
    } <= set(item)


def test_generation_contract_is_strict_versioned_async_and_privacy_safe():
    schemas = SPEC["components"]["schemas"]
    request = schemas["KeywordGenerationRequest"]
    assert request["additionalProperties"] is False
    assert {
        "expected_subject_version_id",
        "expected_keyword_set_version",
        "target_count",
    } <= set(request["required"])
    assert request["properties"]["target_count"]["maximum"] == 200
    assert request["properties"]["regions"]["maxItems"] == 20

    job = schemas["KeywordGenerationJob"]
    assert job["properties"]["status"]["enum"] == [
        "queued",
        "running",
        "retry_wait",
        "succeeded",
        "failed",
        "conflict",
        "superseded",
    ]
    forbidden = {
        "input_digest",
        "request_digest",
        "idempotency_key_digest",
        "input_subject_values",
        "historical_exclusions",
        "output_snapshot",
        "provider_raw_response",
    }
    assert forbidden.isdisjoint(job["properties"])
    response_schema = SPEC["paths"]["/subjects/{subjectId}/keywords/generate"]["post"]["responses"][
        "202"
    ]["content"]["application/json"]["schema"]["$ref"]
    assert response_schema.endswith("/KeywordGenerationJobEnvelope")


def test_distillation_contract_is_versioned_strict_and_privacy_safe():
    paths = SPEC["paths"]
    expected = {
        "/subjects/{subjectId}/distillations",
        "/distillation-jobs/{jobId}",
        "/subjects/{subjectId}/distillations/draft",
        "/subjects/{subjectId}/distillations/current",
        "/subjects/{subjectId}/distillations/confirm",
    }
    assert expected <= set(paths)
    assert {"get", "patch"} <= set(paths["/subjects/{subjectId}/distillations/draft"])

    schemas = SPEC["components"]["schemas"]
    create = schemas["DistillationCreateRequest"]
    draft = schemas["DistillationDraftSaveRequest"]
    assert create["additionalProperties"] is False
    assert draft["additionalProperties"] is False
    assert {"keyword_set_version_id", "expected_workspace_version"} <= set(create["required"])
    assert {"expected_version", "items"} <= set(draft["required"])
    assert schemas["DistillationAction"]["enum"] == ["keep", "merge", "delete", "low_value"]

    job = schemas["DistillationJob"]
    assert job["properties"]["status"]["enum"] == [
        "queued",
        "running",
        "retry_wait",
        "succeeded",
        "failed",
        "conflict",
        "superseded",
    ]
    forbidden = {
        "input_digest",
        "request_digest",
        "idempotency_key_digest",
        "input_subject_values",
        "input_keywords",
        "output_snapshot",
        "provider_raw_response",
        "api_key",
        "prompt",
    }
    assert forbidden.isdisjoint(job["properties"])
    response_ref = paths["/subjects/{subjectId}/distillations"]["post"]["responses"]["202"][
        "content"
    ]["application/json"]["schema"]["$ref"]
    assert response_ref.endswith("/DistillationJobEnvelope")
