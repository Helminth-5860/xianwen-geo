from django.db import transaction

from .catalog import LIMIT_CATALOG
from .models import PlanLimitDefinition


class CatalogSemanticDrift(RuntimeError):
    pass


DISPLAY_FIELDS = {
    "name",
    "category",
    "description",
    "sort_order",
    "required",
    "default_value",
    "status",
    "catalog_version",
}


def catalog_defaults(definition):
    return {
        "name": definition.name,
        "category": definition.category,
        "value_type": definition.value_type,
        "storage_kind": definition.storage_kind,
        "scope": definition.scope,
        "quota_type": definition.quota_type,
        "minimum": definition.minimum,
        "maximum": definition.maximum,
        "unit": definition.unit,
        "required": definition.required,
        "default_value": definition.default,
        "enum_values": list(definition.enum_values),
        "json_schema": definition.json_schema,
        "description": definition.description,
        "status": definition.status,
        "catalog_version": definition.catalog_version,
        "sort_order": definition.sort_order,
        "semantic_digest": definition.semantic_digest,
    }


@transaction.atomic
def synchronize_plan_catalog(*, apply_changes: bool) -> int:
    changes = 0
    for definition in LIMIT_CATALOG:
        current = PlanLimitDefinition.objects.filter(pk=definition.key).first()
        expected = catalog_defaults(definition)
        if current is None:
            changes += 1
            if apply_changes:
                PlanLimitDefinition.objects.create(key=definition.key, **expected)
            continue
        if current.semantic_digest != definition.semantic_digest:
            if current.plan_limits.exists():
                raise CatalogSemanticDrift(
                    f"已使用限制键 {definition.key} 的机器语义发生破坏性变化。"
                )
            changes += 1
            if apply_changes:
                for field, value in expected.items():
                    setattr(current, field, value)
                current.save(update_fields=[*expected, "updated_at"])
            continue
        display_changed = any(
            getattr(current, field) != expected[field] for field in DISPLAY_FIELDS
        )
        if display_changed:
            changes += 1
            if apply_changes:
                for field in DISPLAY_FIELDS:
                    setattr(current, field, expected[field])
                current.save(update_fields=[*DISPLAY_FIELDS, "updated_at"])
    return changes
