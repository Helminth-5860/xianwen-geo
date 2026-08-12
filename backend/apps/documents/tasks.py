import uuid

from celery import shared_task  # type: ignore[import-untyped]
from django.db import InterfaceError, OperationalError

from .parse_services import due_parse_job_ids, execute_parse
from .services import (
    due_expired_intent_ids,
    due_verification_intent_ids,
    expire_upload_intent,
)
from .services import (
    verify_upload_intent as verify_intent,
)


def _request_id(task=None):
    headers = getattr(getattr(task, "request", None), "headers", None) or {}
    return headers.get("request_id") or str(uuid.uuid4())


@shared_task(bind=True, name="documents.verify_upload_intent", max_retries=5)
def verify_upload_intent(self, intent_id):
    try:
        return verify_intent(intent_id=intent_id, request_id=_request_id(self))
    except (OperationalError, InterfaceError) as exc:
        raise self.retry(exc=exc, countdown=min(300, 2 ** (self.request.retries + 1))) from exc


@shared_task(name="documents.scan_verification_retries")
def scan_verification_retries():
    ids = due_verification_intent_ids()
    correlation_id = str(uuid.uuid4())
    for intent_id in ids:
        verify_upload_intent.apply_async(
            args=[str(intent_id)],
            headers={"correlation_id": correlation_id, "request_id": str(uuid.uuid4())},
        )
    return {"queued": len(ids)}


@shared_task(bind=True, name="documents.expire_upload_intent", max_retries=5)
def expire_one_upload_intent(self, intent_id):
    try:
        return expire_upload_intent(intent_id=intent_id, request_id=_request_id(self))
    except (OperationalError, InterfaceError) as exc:
        raise self.retry(exc=exc, countdown=min(300, 2 ** (self.request.retries + 1))) from exc


@shared_task(name="documents.scan_expired_upload_intents")
def scan_expired_upload_intents():
    ids = due_expired_intent_ids()
    correlation_id = str(uuid.uuid4())
    for intent_id in ids:
        expire_one_upload_intent.apply_async(
            args=[str(intent_id)],
            headers={"correlation_id": correlation_id, "request_id": str(uuid.uuid4())},
        )
    return {"queued": len(ids)}


@shared_task(bind=True, name="documents.execute_parse_job", max_retries=5)
def execute_parse_job(self, job_id):
    headers = getattr(self.request, "headers", None) or {}
    try:
        return execute_parse(
            job_id=job_id,
            request_id=headers.get("request_id") or _request_id(self),
            correlation_id=headers.get("correlation_id"),
        )
    except (OperationalError, InterfaceError) as exc:
        raise self.retry(exc=exc, countdown=min(300, 2 ** (self.request.retries + 1))) from exc


@shared_task(name="documents.scan_parse_retries")
def scan_parse_retries():
    ids = due_parse_job_ids()
    correlation_id = str(uuid.uuid4())
    for job_id in ids:
        execute_parse_job.apply_async(
            args=[str(job_id)],
            queue="file_processing",
            headers={"correlation_id": correlation_id, "request_id": str(uuid.uuid4())},
        )
    return {"queued": len(ids)}
