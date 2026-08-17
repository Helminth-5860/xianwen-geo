from decimal import Decimal

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.admin_rbac.models import AuditEvent
from apps.ai.catalog import BUILTIN_AI_MODELS
from apps.ai.errors import AIAdapterError
from apps.ai.models import AIModel, AIModelRuntimeConfig, AIProvider
from apps.ai.registry import AIModelRegistry
from apps.ai.runtime import (
    get_runtime_snapshot,
    list_available_runtime_snapshots,
    resolve_detection_adapter,
)
from apps.users.models import User
from tests.admin_session_helpers import authenticate_admin_client

PASSWORD = "Correct-Horse-Battery-2026!"


@pytest.fixture(autouse=True)
def synchronize_permissions():
    call_command("sync_admin_rbac", "--apply", verbosity=0)


def make_admin():
    suffix = User.objects.count() + 1
    return User.objects.create_superuser(
        phone=f"139{suffix:08d}", nickname="模型配置管理员", password=PASSWORD
    )


def admin_client(*, csrf=False):
    client = APIClient(enforce_csrf_checks=csrf)
    return authenticate_admin_client(client, make_admin())


def data(response):
    return response.json()["data"]


@pytest.mark.django_db
def test_seed_contains_exactly_eight_disabled_builtin_models_and_is_idempotent():
    expected = [item.model_key for item in BUILTIN_AI_MODELS]
    assert (
        list(AIModel.objects.order_by("canonical_order").values_list("model_key", flat=True))
        == expected
    )
    assert AIProvider.objects.count() == 8
    assert AIModel.objects.count() == 8
    assert AIModelRuntimeConfig.objects.count() == 8
    assert not AIModelRuntimeConfig.objects.filter(enabled=True).exists()
    assert not AIModelRuntimeConfig.objects.filter(paused=True).exists()

    call_command("sync_ai_model_catalog", "--apply", verbosity=0)
    assert AIProvider.objects.count() == 8
    assert AIModel.objects.count() == 8
    assert AIModelRuntimeConfig.objects.count() == 8


@pytest.mark.django_db
def test_admin_list_and_detail_expose_fixed_identity_without_secret_fields():
    client = admin_client()
    response = client.get("/api/v1/admin/ai-models")
    assert response.status_code == 200
    rows = data(response)
    assert [row["model_key"] for row in rows] == [item.model_key for item in BUILTIN_AI_MODELS]
    assert response["Cache-Control"] == "no-store"
    assert all("api_key" not in row and "secret" not in row for row in rows)
    detail = client.get(f"/api/v1/admin/ai-models/{rows[0]['model_id']}")
    assert detail.status_code == 200
    runtime = client.get(f"/api/v1/admin/ai-model-runtime-configs/{rows[0]['model_id']}")
    assert runtime.status_code == 200


@pytest.mark.django_db
def test_runtime_update_validates_full_config_uses_version_and_records_safe_audit():
    client = admin_client()
    model = AIModel.objects.get(model_key="deepseek")
    config = model.runtime_config
    response = client.patch(
        f"/api/v1/admin/ai-model-runtime-configs/{model.id}",
        {
            "expected_version": config.version,
            "display_name_override": "  DeepSeek   检测  ",
            "provider_model_id": "deepseek-chat",
            "api_version": "v1",
            "sort_order": 5,
            "network_access_enabled": True,
            "web_search_failure_policy": "degrade_reference",
            "timeout_seconds": 45,
            "max_retries": 4,
            "retry_base_seconds": 10,
            "retry_backoff": "fixed",
            "max_concurrency": 8,
            "cost_unit": "per_million_tokens",
            "currency": "CNY",
            "input_cost": "1.250000",
            "output_cost": "2.500000",
            "request_cost": None,
        },
        format="json",
    )
    assert response.status_code == 200
    row = data(response)
    assert row["display_name"] == "DeepSeek 检测"
    assert row["version"] == 2
    assert row["max_concurrency"] == 8
    assert Decimal(row["input_cost"]) == Decimal("1.250000")

    event = AuditEvent.objects.get(
        category="ai_model_config", action_key="ai_model_config.update", target_id=model.id
    )
    serialized = str(event.safe_after)
    assert "deepseek-chat" not in serialized
    assert "provider_model_configured" in serialized

    stale = client.patch(
        f"/api/v1/admin/ai-model-runtime-configs/{model.id}",
        {"expected_version": 1, "timeout_seconds": 50},
        format="json",
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "AI_MODEL_CONFIG_VERSION_CONFLICT"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        {"timeout_seconds": 0},
        {"max_retries": 11},
        {"retry_base_seconds": 0},
        {"max_concurrency": 0},
        {"currency": "USD"},
        {"display_name_override": "bad\nname"},
        {"cost_unit": "per_request", "request_cost": None},
        {
            "cost_unit": "per_request",
            "request_cost": "1.000000",
            "input_cost": "1.000000",
        },
        {"unknown": True},
    ],
)
def test_runtime_update_rejects_invalid_ranges_cost_shapes_and_unknown_fields(payload):
    client = admin_client()
    model = AIModel.objects.get(model_key="doubao")
    response = client.patch(
        f"/api/v1/admin/ai-model-runtime-configs/{model.id}",
        {"expected_version": model.runtime_config.version, **payload},
        format="json",
    )
    assert response.status_code == 422


@pytest.mark.django_db
def test_enable_disable_pause_unpause_are_explicit_versioned_and_audited():
    client = admin_client()
    model = AIModel.objects.get(model_key="qwen")
    enabled = client.post(
        f"/api/v1/admin/ai-models/{model.id}/enable",
        {"expected_version": 1},
        format="json",
    )
    assert enabled.status_code == 200
    assert data(enabled)["enabled"] is True

    paused = client.post(
        f"/api/v1/admin/ai-models/{model.id}/pause",
        {"expected_version": 2, "reason": "供应商临时维护"},
        format="json",
    )
    assert paused.status_code == 200
    assert data(paused)["paused"] is True
    assert data(paused)["pause_reason"] == "供应商临时维护"

    unpaused = client.post(
        f"/api/v1/admin/ai-models/{model.id}/unpause",
        {"expected_version": 3},
        format="json",
    )
    assert unpaused.status_code == 200
    assert data(unpaused)["pause_reason"] == ""

    disabled = client.post(
        f"/api/v1/admin/ai-models/{model.id}/disable",
        {"expected_version": 4},
        format="json",
    )
    assert disabled.status_code == 200
    assert data(disabled)["enabled"] is False
    assert set(
        AuditEvent.objects.filter(category="ai_model_config", target_id=model.id).values_list(
            "action_key", flat=True
        )
    ) == {"ai_model.enable", "ai_model.pause", "ai_model.unpause", "ai_model.disable"}


@pytest.mark.django_db
def test_pause_requires_reason_and_duplicate_actions_are_state_conflicts():
    client = admin_client()
    model = AIModel.objects.get(model_key="hunyuan")
    missing_reason = client.post(
        f"/api/v1/admin/ai-models/{model.id}/pause",
        {"expected_version": 1, "reason": "  "},
        format="json",
    )
    assert missing_reason.status_code == 422
    same_disabled = client.post(
        f"/api/v1/admin/ai-models/{model.id}/disable",
        {"expected_version": 1},
        format="json",
    )
    assert same_disabled.status_code == 409
    assert same_disabled.json()["error"]["code"] == "AI_MODEL_CONFIG_STATE_CONFLICT"


@pytest.mark.django_db
def test_admin_api_requires_admin_session_permission_and_csrf():
    ordinary = User.objects.create_user(phone="13800138000", nickname="普通用户", password=PASSWORD)
    ordinary_client = APIClient()
    ordinary_client.force_authenticate(ordinary)
    assert ordinary_client.get("/api/v1/admin/ai-models").status_code == 403

    csrf_client = admin_client(csrf=True)
    model = AIModel.objects.get(model_key="wenxin")
    blocked = csrf_client.post(
        f"/api/v1/admin/ai-models/{model.id}/enable",
        {"expected_version": 1},
        format="json",
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "CSRF_FAILED"


@pytest.mark.django_db
def test_runtime_consumption_is_ordered_and_fails_closed_for_disabled_paused_or_missing_adapter():
    deepseek = AIModel.objects.get(model_key="deepseek").runtime_config
    with pytest.raises(AIAdapterError) as disabled:
        get_runtime_snapshot(model_key="deepseek")
    assert disabled.value.stable_code == "AI_MODEL_DISABLED"

    deepseek.enabled = True
    deepseek.version += 1
    deepseek.save()
    snapshot = get_runtime_snapshot(model_key="deepseek")
    assert snapshot.model_key == "deepseek"
    assert [item.model_key for item in list_available_runtime_snapshots()] == ["deepseek"]

    with pytest.raises(AIAdapterError) as missing_adapter:
        resolve_detection_adapter(model_key="deepseek", registry=AIModelRegistry())
    assert missing_adapter.value.stable_code == "AI_UNKNOWN_PROVIDER"

    deepseek.paused = True
    deepseek.pause_reason = "维护"
    deepseek.version += 1
    deepseek.save()
    with pytest.raises(AIAdapterError) as paused:
        get_runtime_snapshot(model_key="deepseek")
    assert paused.value.stable_code == "AI_MODEL_PAUSED"


@pytest.mark.django_db
def test_ai_model_permissions_are_seeded_and_synced():
    from apps.admin_rbac.catalog import CATALOG_BY_KEY
    from apps.admin_rbac.models import AdminPermission

    expected = {"menu.admin.models", "models.list", "models.manage"}
    assert expected <= set(CATALOG_BY_KEY)
    assert expected <= set(AdminPermission.objects.values_list("key", flat=True))
