from billiard.exceptions import SoftTimeLimitExceeded
from celery import shared_task  # type: ignore[import-untyped]
from django.db import InterfaceError, OperationalError

from .browser_services import (
    WebsiteBrowserAuditBusy,
    WebsiteBrowserAuditNotReady,
    execute_browser_audit,
    fail_browser_audit,
    queue_browser_audit,
)
from .models import WebsiteAudit
from .semantic_services import (
    WebsiteSemanticAuditBusy,
    WebsiteSemanticAuditNotReady,
    execute_semantic_audit,
    fail_semantic_audit,
    queue_semantic_audit,
)
from .services import execute_website_audit, fail_website_audit


def _dispatch_semantic_if_ready(audit_id) -> bool:
    if not queue_semantic_audit(audit_id):
        return False
    execute_website_semantic_audit_task.apply_async(
        args=[str(audit_id)],
        queue="ai_content",
    )
    return True


@shared_task(
    bind=True,
    name="website_audits.execute",
    soft_time_limit=90,
    time_limit=105,
)
def execute_website_audit_task(self, audit_id):
    try:
        result = execute_website_audit(audit_id)
        browser_queued = queue_browser_audit(audit_id)
        if browser_queued:
            execute_website_browser_audit_task.apply_async(
                args=[str(audit_id)],
                queue="browser_audit",
            )
        else:
            # Browser auditing can be disabled. Semantic analysis still runs from
            # deterministic/static evidence instead of being silently skipped.
            _dispatch_semantic_if_ready(audit_id)
        return result
    except SoftTimeLimitExceeded:
        fail_website_audit(audit_id, "WEBSITE_AUDIT_TIMEOUT")
        raise
    except (OperationalError, InterfaceError) as exc:
        if self.request.retries >= 3:
            fail_website_audit(audit_id, "WEBSITE_AUDIT_DATABASE_UNAVAILABLE")
            raise
        raise self.retry(
            exc=exc,
            countdown=min(60, 2 ** (self.request.retries + 1)),
            max_retries=3,
        ) from exc
    except Exception:
        fail_website_audit(audit_id)
        raise


@shared_task(bind=True, name="website_audits.execute_browser")
def execute_website_browser_audit_task(self, audit_id):
    try:
        result = execute_browser_audit(audit_id)
        _dispatch_semantic_if_ready(audit_id)
        return result
    except WebsiteBrowserAuditBusy:
        status = WebsiteAudit.objects.filter(pk=audit_id).values_list(
            "browser_status", flat=True
        ).first()
        return {"audit_id": str(audit_id), "browser_status": status or "running"}
    except WebsiteBrowserAuditNotReady:
        status = WebsiteAudit.objects.filter(pk=audit_id).values_list(
            "browser_status", flat=True
        ).first()
        return {"audit_id": str(audit_id), "browser_status": status or "not_ready"}
    except (OperationalError, InterfaceError) as exc:
        if self.request.retries >= 2:
            fail_browser_audit(audit_id, "BROWSER_DATABASE_UNAVAILABLE")
            _dispatch_semantic_if_ready(audit_id)
            raise
        raise self.retry(
            exc=exc,
            countdown=min(60, 2 ** (self.request.retries + 1)),
            max_retries=2,
        ) from exc
    except Exception:
        fail_browser_audit(audit_id)
        # Browser failure must not erase the deeper content audit; semantic analysis
        # can still use M1/M2 evidence and records browser_status=failed as evidence.
        _dispatch_semantic_if_ready(audit_id)
        raise


@shared_task(bind=True, name="website_audits.execute_semantic")
def execute_website_semantic_audit_task(self, audit_id):
    try:
        return execute_semantic_audit(audit_id)
    except WebsiteSemanticAuditBusy:
        status = WebsiteAudit.objects.filter(pk=audit_id).values_list(
            "semantic_status", flat=True
        ).first()
        return {"audit_id": str(audit_id), "semantic_status": status or "running"}
    except WebsiteSemanticAuditNotReady:
        status = WebsiteAudit.objects.filter(pk=audit_id).values_list(
            "semantic_status", flat=True
        ).first()
        return {"audit_id": str(audit_id), "semantic_status": status or "not_ready"}
    except (OperationalError, InterfaceError) as exc:
        if self.request.retries >= 2:
            fail_semantic_audit(audit_id, "SEMANTIC_DATABASE_UNAVAILABLE")
            raise
        raise self.retry(
            exc=exc,
            countdown=min(60, 2 ** (self.request.retries + 1)),
            max_retries=2,
        ) from exc
    except Exception:
        current = WebsiteAudit.objects.filter(pk=audit_id).values_list(
            "semantic_status", flat=True
        ).first()
        if current != WebsiteAudit.SemanticStatus.FAILED:
            fail_semantic_audit(audit_id)
        raise
