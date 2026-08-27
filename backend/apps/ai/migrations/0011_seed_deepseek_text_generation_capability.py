from django.db import migrations


def seed_deepseek_text_generation(apps, schema_editor):
    Provider = apps.get_model("ai", "AIProvider")
    Model = apps.get_model("ai", "AIModel")
    ModelRuntime = apps.get_model("ai", "AIModelRuntimeConfig")
    CapabilityRuntime = apps.get_model("ai", "AICapabilityRuntimeConfig")
    Binding = apps.get_model("ai", "APICredentialCapabilityBinding")

    provider = Provider.objects.get(provider_key="deepseek")
    model = Model.objects.get(model_key="deepseek", provider=provider)
    model_runtime = ModelRuntime.objects.get(model=model)
    CapabilityRuntime.objects.get_or_create(
        model=model,
        capability="text_generation",
        defaults={
            "provider_model_id": model_runtime.provider_model_id,
            "api_version": model_runtime.api_version,
            "enabled": model_runtime.enabled,
            "paused": model_runtime.paused,
            "pause_reason": model_runtime.pause_reason,
            "timeout_seconds": 120,
            "max_retries": model_runtime.max_retries,
            "retry_base_seconds": model_runtime.retry_base_seconds,
        },
    )
    for environment in ("staging", "production"):
        Binding.objects.get_or_create(
            provider=provider,
            capability="text_generation",
            environment=environment,
            defaults={"enabled": False},
        )


class Migration(migrations.Migration):
    dependencies = [("ai", "0010_seed_deepseek_question_generation_capability")]

    operations = [
        migrations.RunPython(
            seed_deepseek_text_generation,
            migrations.RunPython.noop,
        )
    ]
