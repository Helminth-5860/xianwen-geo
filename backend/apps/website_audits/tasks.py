from celery import shared_task  # type: ignore[import-untyped]
from django.db import InterfaceError, OperationalError

from .services import execute_website_audit, fail_website_audit


@shared_task(bind=True, name="website_audits.execute")
def execute_website_audit_task(self, audit_id):
    try:
        return execute_website_audit(audit_id)
    except (OperationalError, InterfaceError) as exc:
        if self.request.retries >= 3:
            fail_website_audit(audit_id, "WEBSITE_AUDIT_DATABASE_UNAVAILABLE")
            raise
        raise self.retry(exc=exc, countdown=min(60, 2 ** (self.request.retries + 1)), max_retries=3) from exc
    except Exception:
        fail_website_audit(audit_id)
        raise
