from pathlib import Path

import yaml

SPEC_PATH = Path(__file__).resolve().parents[2] / "openapi" / "openapi-v1.yaml"


def test_ai_model_config_openapi_exposes_only_frozen_admin_operations():
    spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    paths = spec["paths"]
    expected = {
        "/admin/ai-models": {"get"},
        "/admin/ai-models/{modelId}": {"get", "parameters"},
        "/admin/ai-models/{modelId}/enable": {"post", "parameters"},
        "/admin/ai-models/{modelId}/disable": {"post", "parameters"},
        "/admin/ai-models/{modelId}/pause": {"post", "parameters"},
        "/admin/ai-models/{modelId}/unpause": {"post", "parameters"},
        "/admin/ai-model-runtime-configs": {"get"},
        "/admin/ai-model-runtime-configs/{modelId}": {"get", "patch", "parameters"},
    }
    for path, operations in expected.items():
        assert path in paths
        assert set(paths[path]) == operations
        assert "delete" not in paths[path]
    assert "post" not in paths["/admin/ai-models"]


def test_ai_model_config_openapi_is_strict_versioned_and_has_no_secret_fields():
    spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    schemas = spec["components"]["schemas"]
    update = schemas["AIModelRuntimeConfigUpdateRequest"]
    assert update["additionalProperties"] is False
    assert update["required"] == ["expected_version"]
    assert "enabled" not in update["properties"]
    assert "paused" not in update["properties"]
    assert "provider_key" not in update["properties"]
    assert "model_key" not in update["properties"]
    serialized = str(schemas["AIModelRuntimeConfig"]).lower()
    assert "api_key" not in serialized
    assert "secret" not in serialized
    assert schemas["PauseAIModelRequest"]["required"] == ["expected_version", "reason"]
