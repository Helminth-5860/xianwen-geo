import uuid

from celery import shared_task  # type: ignore[import-untyped]
from django.db import InterfaceError, OperationalError

from .lifecycle import advance_cycle_account, due_cycle_account_ids


@shared_task(name="quotas.scan_due_cycles")
def scan_due_cycles():
    correlation_id = str(uuid.uuid4())
    ids = due_cycle_account_ids()
    for account_id in ids:
        advance_cycle.apply_async(
            args=[str(account_id)],
            headers={"correlation_id": correlation_id, "request_id": str(uuid.uuid4())},
        )
    return {"queued": len(ids)}


@shared_task(bind=True, name="quotas.advance_cycle", max_retries=5)
def advance_cycle(self, account_id):
    headers = getattr(self.request, "headers", None) or {}
    request_id = headers.get("request_id") or str(uuid.uuid4())
    try:
        advance_cycle_account(account_id=account_id, request_id=request_id)
    except (OperationalError, InterfaceError) as exc:
        raise self.retry(exc=exc, countdown=min(300, 2 ** (self.request.retries + 1))) from exc
    return {"processed": True}
