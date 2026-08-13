import uuid

from celery import shared_task  # type: ignore[import-untyped]
from django.conf import settings
from django.db import InterfaceError, OperationalError

from .exceptions import WebSourceUnexpectedError
from .services import due_import_ids, execute_import, fail_internal_import


def _request_id(task):
    headers = getattr(task.request, "headers", None) or {}
    return headers.get("request_id") or str(uuid.uuid4())


@shared_task(bind=True, name="web_sources.execute_import")
def execute_import_task(self, import_id, generation=None):
    try:
        return execute_import(import_id=import_id, expected_generation=generation)
    except WebSourceUnexpectedError as exc:
        maximum = settings.WEB_IMPORT_INTERNAL_MAX_RETRIES
        if self.request.retries >= maximum:
            return fail_internal_import(import_id=exc.import_id, generation=exc.generation)
        raise self.retry(
            args=[str(exc.import_id), str(exc.generation)],
            countdown=min(300, 2 ** (self.request.retries + 1)),
            max_retries=maximum,
        ) from exc
    except (OperationalError, InterfaceError) as exc:
        raise self.retry(
            exc=exc,
            countdown=min(300, 2 ** (self.request.retries + 1)),
            max_retries=settings.WEB_IMPORT_INTERNAL_MAX_RETRIES,
        ) from exc


def _dispatch():
    ids = due_import_ids()
    correlation_id = str(uuid.uuid4())
    for import_id in ids:
        execute_import_task.apply_async(
            args=[str(import_id)],
            queue="web_fetch",
            headers={"request_id": str(uuid.uuid4()), "correlation_id": correlation_id},
        )
    return {"queued": len(ids)}


@shared_task(name="web_sources.dispatch_queued_imports")
def dispatch_queued_imports():
    return _dispatch()


@shared_task(name="web_sources.scan_import_retries")
def scan_import_retries():
    return _dispatch()
