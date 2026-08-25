from django.db import migrations


def seed_deepseek_semantic_scoring(apps, schema_editor):
    Provider = apps.get_model("ai", "AIProvider")
    Model = apps.get_model("ai", "AIModel")
    Runtime = apps.get_model("ai", "AICapabilityRuntimeConfig")
    Binding = apps.get_model("ai", "APICredentialCapabilityBinding")

    provider = Provider.objects.get(provider_key="deepseek")
    model = Model.objects.get(model_key="deepseek", provider=provider)

    Runtime.objects.get_or_create(
        model=model,
        capability="semantic_scoring",
        defaults={
            "provider_model_id": "deepseek-chat",
            "api_version": "",
            "enabled": True,
            "paused": False,
            "pause_reason": "",
            "timeout_seconds": 120,
            "max_retries": 2,
            "retry_base_seconds": 30,
        },
    )

    Binding.objects.get_or_create(
        provider=provider,
        capability="semantic_scoring",
        environment="staging",
        defaults={"enabled": True},
    )
    Binding.objects.get_or_create(
        provider=provider,
        capability="semantic_scoring",
        environment="production",
        defaults={"enabled": False},
    )


class Migration(migrations.Migration):
    dependencies = [("ai", "0006_seed_deepseek_keyword_generation_capability")]

    operations = [
        migrations.RunPython(
            seed_deepseek_semantic_scoring,
            migrations.RunPython.noop,
        )
    ]
