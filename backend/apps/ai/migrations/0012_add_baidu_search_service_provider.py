from django.db import migrations, models


PROVIDER_KEYS = (
    "deepseek",
    "doubao",
    "qwen",
    "hunyuan",
    "wenxin",
    "kimi",
    "glm",
    "spark",
    "baidu_search",
)


def seed_baidu_search_provider(apps, schema_editor):
    Provider = apps.get_model("ai", "AIProvider")
    Provider.objects.update_or_create(
        provider_key="baidu_search",
        defaults={"canonical_name": "百度搜索", "is_builtin": True},
    )


def unseed_baidu_search_provider(apps, schema_editor):
    Provider = apps.get_model("ai", "AIProvider")
    Credential = apps.get_model("ai", "APICredential")
    provider = Provider.objects.filter(provider_key="baidu_search").first()
    if provider is None:
        return
    if Credential.objects.filter(provider=provider).exists():
        raise RuntimeError(
            "Cannot reverse Baidu Search provider migration while credentials still reference it."
        )
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("ALTER TABLE ai_providers DISABLE TRIGGER ai_provider_guard")
        try:
            provider.delete()
        finally:
            schema_editor.execute("ALTER TABLE ai_providers ENABLE TRIGGER ai_provider_guard")
    else:
        provider.delete()


class Migration(migrations.Migration):
    dependencies = [("ai", "0011_seed_deepseek_text_generation_capability")]

    operations = [
        migrations.RemoveConstraint(
            model_name="aiprovider",
            name="ai_provider_fixed_key",
        ),
        migrations.AddConstraint(
            model_name="aiprovider",
            constraint=models.CheckConstraint(
                condition=models.Q(provider_key__in=PROVIDER_KEYS),
                name="ai_provider_fixed_key",
            ),
        ),
        migrations.RunPython(seed_baidu_search_provider, unseed_baidu_search_provider),
    ]
