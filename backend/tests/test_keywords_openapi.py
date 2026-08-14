from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = yaml.safe_load((ROOT / "openapi/openapi-v1.yaml").read_text(encoding="utf-8"))


def test_keyword_editor_paths_exist_without_xw0302_implementation_routes():
    paths = SPEC["paths"]
    expected = {
        "/subjects/{subjectId}/keywords/draft",
        "/subjects/{subjectId}/keywords/current",
        "/subjects/{subjectId}/keywords/commit",
        "/subjects/{subjectId}/keywords/versions",
        "/subjects/{subjectId}/keywords/versions/{versionId}",
    }
    assert expected <= set(paths)
    assert "patch" in paths["/subjects/{subjectId}/keywords/draft"]
    assert "post" in paths["/subjects/{subjectId}/keywords/commit"]


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
    commit_envelope = schemas["KeywordCommitEnvelope"]
    commit_data = commit_envelope["allOf"][1]["properties"]["data"]["properties"]
    assert "keyword_set_version" not in commit_data
