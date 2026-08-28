# ruff: noqa: E501
import pytest
from django.core.management import call_command
from django.db import DatabaseError, IntegrityError, connection, transaction

from apps.ai.catalog import BUILTIN_AI_MODELS, BUILTIN_PROVIDER_KEYS
from apps.ai.models import AIModel, AIModelRuntimeConfig, AIProvider

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="PostgreSQL AI model configuration guards require PostgreSQL.",
    ),
]


@pytest.fixture(autouse=True)
def synchronize_builtin_catalog():
    call_command("sync_ai_model_catalog", "--apply", verbosity=0)


def test_seed_has_builtin_provider_model_and_runtime_rows():
    assert AIProvider.objects.count() == len(BUILTIN_PROVIDER_KEYS)
    assert AIModel.objects.count() == len(BUILTIN_AI_MODELS)
    assert AIModelRuntimeConfig.objects.count() == len(BUILTIN_AI_MODELS)


def test_builtin_provider_and_model_identity_and_delete_are_database_protected():
    model = AIModel.objects.get(model_key="deepseek")
    provider = model.provider
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE ai_models SET model_key = %s WHERE id = %s", ["changed", model.id]
            )
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM ai_models WHERE id = %s", [model.id])
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE ai_providers SET canonical_name = %s WHERE id = %s",
                ["Changed", provider.id],
            )


def test_model_provider_identity_mismatch_is_database_protected():
    deepseek = AIModel.objects.get(model_key="deepseek")
    doubao_provider = AIProvider.objects.get(provider_key="doubao")
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE ai_models SET provider_id = %s WHERE id = %s",
                [doubao_provider.id, deepseek.id],
            )


def test_runtime_binding_delete_and_version_increment_are_database_protected():
    config = AIModelRuntimeConfig.objects.get(model__model_key="qwen")
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE ai_model_runtime_configs SET timeout_seconds = %s WHERE id = %s",
                [40, config.id],
            )
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE ai_model_runtime_configs SET timeout_seconds = %s, version = version + 1 WHERE id = %s",
                [40, config.id],
            )
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM ai_model_runtime_configs WHERE id = %s", [config.id])


def test_runtime_database_constraints_reject_invalid_ranges_and_cost_shape():
    config = AIModelRuntimeConfig.objects.get(model__model_key="spark")
    with pytest.raises(IntegrityError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE ai_model_runtime_configs SET timeout_seconds = 0, version = version + 1 WHERE id = %s",
                [config.id],
            )
    with pytest.raises(IntegrityError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE ai_model_runtime_configs SET cost_unit = %s, request_cost = NULL, version = version + 1 WHERE id = %s",
                ["per_request", config.id],
            )
