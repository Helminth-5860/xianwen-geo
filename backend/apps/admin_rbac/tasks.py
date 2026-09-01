from celery import shared_task  # type: ignore[import-untyped]

from .sensitive_audit_services import purge_expired_sensitive_audit_logs


@shared_task(name="admin_rbac.purge_sensitive_audit_logs")
def purge_sensitive_audit_logs_task() -> int:
    return purge_expired_sensitive_audit_logs()
