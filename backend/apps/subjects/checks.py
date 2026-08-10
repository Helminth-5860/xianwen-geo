from django.core.checks import Error, Tags, register
from django.db import OperationalError, ProgrammingError, connection
from django.db.migrations.recorder import MigrationRecorder

from .catalog_services import CatalogSemanticDrift, synchronize_subject_catalog


@register(Tags.models)
def subject_catalog_check(app_configs, **kwargs):
    try:
        tables = set(connection.introspection.table_names())
        catalog_seed_applied = (
            MigrationRecorder(connection)
            .migration_qs.filter(app="subjects", name="0002_seed_builtin_subject_catalog")
            .exists()
        )
    except (OperationalError, ProgrammingError):
        return []
    if "subject_types" not in tables or not catalog_seed_applied:
        return []
    try:
        changes = synchronize_subject_catalog(apply_changes=False)
    except CatalogSemanticDrift as exc:
        return [Error(str(exc), id="subjects.E001")]
    if changes:
        return [
            Error(
                "主体类型目录未同步，请执行 sync_subject_catalog --apply。",
                id="subjects.E002",
            )
        ]
    return []
