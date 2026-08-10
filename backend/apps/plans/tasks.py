import uuid

from celery import shared_task  # type: ignore[import-untyped]
from django.db import InterfaceError, OperationalError

from .lifecycle import due_expiry_ids, due_renewal_ids, execute_due_renewal, expire_subscription


def _headers(task):
    headers = getattr(task.request, "headers", None) or {}
    correlation_id = headers.get("correlation_id") or str(uuid.uuid4())
    return {"correlation_id": correlation_id, "request_id": str(uuid.uuid4())}


@shared_task(name="plans.scan_due_renewals")
def scan_due_renewals():
    correlation_id = str(uuid.uuid4())
    ids = due_renewal_ids()
    for change_id in ids:
        execute_renewal.apply_async(
            args=[str(change_id)],
            headers={"correlation_id": correlation_id, "request_id": str(uuid.uuid4())},
        )
    return {"queued": len(ids)}


@shared_task(bind=True, name="plans.execute_due_renewal", max_retries=5)
def execute_renewal(self, change_id):
    headers = _headers(self)
    try:
        execute_due_renewal(change_id=change_id, request_id=headers["request_id"])
    except (OperationalError, InterfaceError) as exc:
        raise self.retry(exc=exc, countdown=min(300, 2 ** (self.request.retries + 1))) from exc
    return {"processed": True}


@shared_task(name="plans.scan_due_expiries")
def scan_due_expiries():
    correlation_id = str(uuid.uuid4())
    ids = due_expiry_ids()
    for subscription_id in ids:
        expire_due_subscription.apply_async(
            args=[str(subscription_id)],
            headers={"correlation_id": correlation_id, "request_id": str(uuid.uuid4())},
        )
    return {"queued": len(ids)}


@shared_task(bind=True, name="plans.expire_due_subscription", max_retries=5)
def expire_due_subscription(self, subscription_id):
    headers = _headers(self)
    try:
        expire_subscription(subscription_id=subscription_id, request_id=headers["request_id"])
    except (OperationalError, InterfaceError) as exc:
        raise self.retry(exc=exc, countdown=min(300, 2 ** (self.request.retries + 1))) from exc
    return {"processed": True}
