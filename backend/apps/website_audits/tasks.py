from celery import shared_task  # type: ignore[import-untyped]
from django.db import InterfaceError, OperationalError

from .browser_services import execute_browser_audit, fail_browser_audit, queue_browser_audit
from .services import execute_website_audit, fail_website_audit


@shared_task(bind=True, name="website_audits.execute")
def execute_website_audit_task(self, audit_id):
    try:
        result = execute_website_audit(audit_id)
        if queue_browser_audit(audit_id):
            execute_website_browser_audit_task.apply_async(
                args=[str(audit_id)],
                queue="browser_audit",
            )
        return result
    except (OperationalError, InterfaceError) as exc:
        if self.request.retries >= 3:
            fail_website_audit(audit_id, "WEBSITE_AUDIT_DATABASE_UNAVAILABLE")
            raise
        raise self.retry(exc=exc, countdown=min(60, 2 ** (self.request.retries + 1)), max_retries=3) from exc
    except Exception:
        fail_website_audit(audit_id)
        raise


@shared_task(bind=True, name="website_audits.execute_browser")
def execute_website_browser_audit_task(self, audit_id):
    try:
        return execute_browser_audit(audit_id)
    except (OperationalError, InterfaceError) as exc:
        if self.request.retries >= 2:
            fail_browser_audit(audit_id, "BROWSER_DATABASE_UNAVAILABLE")
            raise
        raise self.retry(exc=exc, countdown=min(60, 2 ** (self.request.retries + 1)), max_retries=2) from exc
    except Exception:
        fail_browser_audit(audit_id)
        raise
