from django.db import migrations


def seed_deepseek_keyword_generation(apps, schema_editor):
    Provider = apps.get_model("ai", "AIProvider")
    Model = apps.get_model("ai", "AIModel")
    Runtime = apps.get_model("ai", "AICapabilityRuntimeConfig")
    Binding = apps.get_model("ai", "APICredentialCapabilityBinding")

    provider = Provider.objects.get(provider_key="deepseek")
    model = Model.objects.get(model_key="deepseek", provider=provider)
    Runtime.objects.get_or_create(
        model=model,
        capability="keyword_generation",
        defaults={
            "provider_model_id": "",
            "api_version": "",
            "enabled": False,
            "paused": False,
            "pause_reason": "",
            "timeout_seconds": 120,
            "max_retries": 2,
            "retry_base_seconds": 30,
        },
    )
    for environment in ("staging", "production"):
        Binding.objects.get_or_create(
            provider=provider,
            capability="keyword_generation",
            environment=environment,
            defaults={"enabled": False},
        )


class Migration(migrations.Migration):
    dependencies = [("ai", "0005_aicapabilityruntimeconfig_and_more")]

    operations = [
        migrations.RunPython(
            seed_deepseek_keyword_generation,
            migrations.RunPython.noop,
        )
    ]
