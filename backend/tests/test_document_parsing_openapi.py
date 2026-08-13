from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = yaml.safe_load((ROOT / "openapi/openapi-v1.yaml").read_text(encoding="utf-8"))


def test_document_parse_paths_are_strict_session_csrf_contracts():
    paths = SPEC["paths"]
    assert {
        "/documents/{documentId}/parse",
        "/documents/{documentId}/parse-result",
        "/documents/{documentId}/confirm",
    } <= paths.keys()
    parse = paths["/documents/{documentId}/parse"]["post"]
    confirm = paths["/documents/{documentId}/confirm"]["post"]
    assert {item["$ref"] for item in parse["parameters"]} >= {
        "#/components/parameters/CsrfToken",
        "#/components/parameters/IdempotencyKey",
    }
    assert {item["$ref"] for item in confirm["parameters"]} == {"#/components/parameters/CsrfToken"}
    assert set(parse["responses"]) == {"202", "401", "403", "404", "409", "422", "503"}
    assert set(confirm["responses"]) == {"200", "401", "403", "404", "409", "422"}


def test_parse_and_confirm_requests_reject_unknown_or_internal_fields():
    schemas = SPEC["components"]["schemas"]
    parse = schemas["DocumentParseRequest"]
    confirm = schemas["DocumentParseConfirmRequest"]
    assert parse["additionalProperties"] is False
    assert set(parse["properties"]) == {"document_version_id"}
    assert confirm["additionalProperties"] is False
    assert set(confirm["properties"]) == {
        "expected_parse_state_version",
        "source_parsed_version_id",
        "confirmed_text",
    }
    forbidden = {
        "tables",
        "warnings",
        "parser_key",
        "ocr_provider",
        "digest",
        "version_no",
        "object_key",
        "task_id",
    }
    assert forbidden.isdisjoint(parse["properties"])
    assert forbidden.isdisjoint(confirm["properties"])


def test_parse_result_exposes_only_safe_bounded_projection():
    result = SPEC["components"]["schemas"]["DocumentParseResult"]
    assert result["additionalProperties"] is False
    forbidden = {
        "object_key",
        "bucket",
        "sha256",
        "content_digest",
        "idempotency_key_digest",
        "generation",
        "lease",
        "task_id",
        "raw_exception",
        "ocr_raw_response",
        "actor",
    }
    assert forbidden.isdisjoint(result["properties"])
    assert result["properties"]["tables"]["type"] == "array"
    assert (
        "Cache-Control"
        in SPEC["paths"]["/documents/{documentId}/parse-result"]["get"]["responses"]["200"][
            "headers"
        ]
    )


def test_xw0206_adds_no_force_reparse_web_import_or_reset_endpoint():
    paths = set(SPEC["paths"])
    assert not any("force-reparse" in path for path in paths)
    assert not any("web-import" in path or "url-import" in path for path in paths)
    assert not any("parse/reset" in path or "parse/execute" in path for path in paths)
