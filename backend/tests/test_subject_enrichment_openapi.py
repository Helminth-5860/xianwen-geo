from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = yaml.safe_load((ROOT / "openapi/openapi-v1.yaml").read_text(encoding="utf-8"))


def test_enrichment_openapi_paths_are_strict_and_owner_scoped():
    paths = SPEC["paths"]
    create = paths["/subjects/{subjectId}/ai-enrichment"]["post"]
    confirm = paths["/subjects/{subjectId}/ai-enrichment/{jobId}/confirm"]["post"]
    assert any(item.get("$ref", "").endswith("/IdempotencyKey") for item in create["parameters"])
    assert any(item.get("$ref", "").endswith("/CsrfToken") for item in create["parameters"])
    assert any(item.get("$ref", "").endswith("/CsrfToken") for item in confirm["parameters"])
    create_schema = SPEC["components"]["schemas"]["SubjectEnrichmentCreateRequest"]
    confirm_schema = SPEC["components"]["schemas"]["SubjectEnrichmentConfirmRequest"]
    assert create_schema["additionalProperties"] is False
    assert create_schema["properties"]["sources"]["maxItems"] == 8
    assert "minItems" not in create_schema["properties"]["sources"]
    assert create_schema["properties"]["target_field_keys"]["maxItems"] == 20
    assert confirm_schema["additionalProperties"] is False
    assert "job_id" not in confirm_schema["properties"]


def test_source_listing_does_not_cap_available_history_to_eight():
    sources = SPEC["components"]["schemas"]["SubjectEnrichmentSources"]["properties"]["sources"]
    assert "maxItems" not in sources


def test_safe_job_projection_excludes_sensitive_ai_inputs():
    props = SPEC["components"]["schemas"]["SubjectEnrichmentJob"]["properties"]
    for forbidden in (
        "prompt",
        "input_digest",
        "output_digest",
        "raw_response",
        "input_subject_values",
    ):
        assert forbidden not in props
