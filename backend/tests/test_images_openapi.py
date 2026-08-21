from pathlib import Path

import yaml

SPEC = yaml.safe_load(
    (Path(__file__).resolve().parents[2] / "openapi" / "openapi-v1.yaml").read_text(
        encoding="utf-8"
    )
)


def test_image_wave_routes_and_private_asset_contract_are_documented():
    paths = SPEC["paths"]
    expected = {
        "/image-sizes",
        "/image-styles",
        "/articles/{articleId}/image-recommendations",
        "/subjects/{subjectId}/images/generate",
        "/image-jobs/{jobId}",
        "/subjects/{subjectId}/images",
        "/images/{imageId}/save-to-library",
        "/images/{imageId}/attach",
        "/images/{imageId}/derive",
        "/images/batch-download",
        "/images/{imageId}",
        "/images/{imageId}/restore",
        "/images/{imageId}/moderation/appeal",
        "/admin/ai-capability-runtimes",
        "/admin/api-credential-bindings/{providerKey}",
    }
    assert expected.issubset(paths)
    image = SPEC["components"]["schemas"]["ImageAsset"]
    assert "url" in image["properties"]
    forbidden = {"provider_url", "raw_provider_json", "authorization", "api_key", "prompt"}
    assert forbidden.isdisjoint(image["properties"])
    job = SPEC["components"]["schemas"]["ImageJob"]
    assert forbidden.isdisjoint(job["properties"])


def test_image_generate_requires_csrf_and_hmac_idempotency_header():
    operation = SPEC["paths"]["/subjects/{subjectId}/images/generate"]
    refs = {
        parameter.get("$ref")
        for parameter in [*operation["parameters"], *operation["post"]["parameters"]]
        if isinstance(parameter, dict)
    }
    assert "#/components/parameters/IdempotencyKey" in refs
    assert "#/components/parameters/CsrfToken" in refs
    responses = operation["post"]["responses"]
    assert {"202", "409", "422", "503"}.issubset(responses)
