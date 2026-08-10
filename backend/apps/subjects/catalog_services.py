from django.db import transaction

from .catalog import COMMON_FIELD_CATALOG, SUBJECT_TYPE_CATALOG
from .models import SubjectFieldDefinition, SubjectType, SubjectTypeFieldConfig


class CatalogSemanticDrift(RuntimeError):
    pass


def _definition_semantics(definition):
    return (
        definition.field_key,
        definition.field_type,
        definition.scope,
        definition.owner_subject_type_id,
        definition.is_builtin,
    )


@transaction.atomic
def synchronize_subject_catalog(*, apply_changes: bool) -> int:
    changes = 0
    common_definitions: dict[str, SubjectFieldDefinition] = {}
    for field in COMMON_FIELD_CATALOG:
        current = SubjectFieldDefinition.objects.filter(
            scope=SubjectFieldDefinition.Scope.COMMON,
            owner_subject_type__isnull=True,
            field_key=field.key,
        ).first()
        if current is None:
            changes += 1
            if apply_changes:
                current = SubjectFieldDefinition.objects.create(
                    field_key=field.key,
                    field_type=field.field_type,
                    scope=SubjectFieldDefinition.Scope.COMMON,
                    is_builtin=True,
                )
        elif _definition_semantics(current) != (
            field.key,
            field.field_type,
            SubjectFieldDefinition.Scope.COMMON,
            None,
            True,
        ):
            raise CatalogSemanticDrift(f"公共字段 {field.key} 的机器语义发生变化。")
        if current is not None:
            common_definitions[field.key] = current

    for item in SUBJECT_TYPE_CATALOG:
        subject_type = SubjectType.objects.filter(key=item.key).first()
        if subject_type is None:
            changes += 1
            if apply_changes:
                subject_type = SubjectType.objects.create(
                    key=item.key,
                    name=item.name,
                    description=item.description,
                    icon_key=item.icon_key,
                    status=SubjectType.Status.ACTIVE,
                    sort_order=item.sort_order,
                    is_builtin=True,
                )
            created = True
        else:
            created = False
        if subject_type is not None and (
            not subject_type.is_builtin or subject_type.key != item.key
        ):
            raise CatalogSemanticDrift(f"内置主体类型 {item.key} 的机器语义发生变化。")
        if subject_type is None:
            changes += len(COMMON_FIELD_CATALOG)
            continue
        added_config = False
        for field in COMMON_FIELD_CATALOG:
            definition = common_definitions.get(field.key)
            if definition is None:
                continue
            if SubjectTypeFieldConfig.objects.filter(
                subject_type=subject_type,
                field_definition=definition,
            ).exists():
                continue
            changes += 1
            if apply_changes:
                SubjectTypeFieldConfig.objects.create(
                    subject_type=subject_type,
                    field_definition=definition,
                    label=field.label,
                    description=field.description,
                    required=field.required,
                    default_value=None,
                    sort_order=field.sort_order,
                    enabled=True,
                    used_for_ai=field.used_for_ai,
                    name_role=field.name_role,
                )
                added_config = True
        if apply_changes and added_config and not created:
            SubjectType.objects.filter(pk=subject_type.pk).update(
                schema_version=subject_type.schema_version + 1
            )
    return changes
