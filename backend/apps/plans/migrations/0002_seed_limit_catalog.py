# The JSON file is the code-owned catalog source. Reverse is intentionally noop.

from django.db import migrations


def seed_catalog(apps, schema_editor):
    from apps.plans.catalog import LIMIT_CATALOG

    Definition = apps.get_model("plans", "PlanLimitDefinition")
    for item in LIMIT_CATALOG:
        Definition.objects.update_or_create(
            key=item.key,
            defaults={
                "name": item.name,
                "category": item.category,
                "value_type": item.value_type,
                "storage_kind": item.storage_kind,
                "scope": item.scope,
                "quota_type": item.quota_type,
                "minimum": item.minimum,
                "maximum": item.maximum,
                "unit": item.unit,
                "required": item.required,
                "default_value": item.default,
                "enum_values": list(item.enum_values),
                "json_schema": item.json_schema,
                "description": item.description,
                "status": item.status,
                "catalog_version": item.catalog_version,
                "sort_order": item.sort_order,
                "semantic_digest": item.semantic_digest,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("plans", "0001_initial")]
    operations = [migrations.RunPython(seed_catalog, migrations.RunPython.noop)]
