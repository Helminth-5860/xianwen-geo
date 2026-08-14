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


@register(Tags.security)
def subject_enrichment_configuration_check(app_configs, **kwargs):
    from django.conf import settings

    provider = settings.SUBJECT_ENRICHMENT_PROVIDER
    if provider not in {"mock", "unavailable"}:
        return [Error("Unsupported subject enrichment provider.", id="subjects.E020")]
    if getattr(settings, "APP_ENV", "local") == "production" and provider == "mock":
        return [
            Error(
                "Mock subject enrichment provider is forbidden in production.", id="subjects.E021"
            )
        ]
    return []
