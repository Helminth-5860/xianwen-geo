from django.db import migrations
from django.db.models import F


def use_deepseek_v4_flash_for_semantic_scoring(apps, schema_editor):
    Provider = apps.get_model("ai", "AIProvider")
    Model = apps.get_model("ai", "AIModel")
    Runtime = apps.get_model("ai", "AICapabilityRuntimeConfig")

    provider = Provider.objects.get(provider_key="deepseek")
    model = Model.objects.get(model_key="deepseek", provider=provider)

    # 0007 originally seeded the compatibility alias `deepseek-chat`. DeepSeek's
    # current semantic-scoring runtime is V4 Flash. Update only the untouched seed
    # value so an operator's explicit runtime choice is never overwritten.
    Runtime.objects.filter(
        model=model,
        capability="semantic_scoring",
        provider_model_id="deepseek-chat",
    ).update(
        provider_model_id="deepseek-v4-flash",
        version=F("version") + 1,
    )


class Migration(migrations.Migration):
    dependencies = [("ai", "0007_seed_deepseek_semantic_scoring_capability")]

    operations = [
        migrations.RunPython(
            use_deepseek_v4_flash_for_semantic_scoring,
            migrations.RunPython.noop,
        )
    ]
