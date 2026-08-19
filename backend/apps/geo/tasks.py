from __future__ import annotations

import logging
import uuid

from celery import shared_task  # type: ignore[import-untyped]
from django.conf import settings
from django.db import InterfaceError, OperationalError

from .services import (
    due_model_call_ids,
    execute_model_call,
    expire_queue_timeouts,
    expire_stale_running_calls,
    fail_internal_model_call,
)

logger = logging.getLogger("xianwen.geo")


@shared_task(bind=True, name="geo.execute_model_call")
def execute_model_call_task(self, call_id):
    try:
        return execute_model_call(call_id=call_id)
    except (OperationalError, InterfaceError) as exc:
        if self.request.retries >= settings.GEO_DETECTION_INTERNAL_MAX_RETRIES:
            return fail_internal_model_call(call_id=call_id)
        raise self.retry(
            args=[str(call_id)],
            exc=exc,
            countdown=min(60, 2 ** (self.request.retries + 1)),
            max_retries=settings.GEO_DETECTION_INTERNAL_MAX_RETRIES,
        ) from exc
    except Exception:
        logger.exception(
            "geo detection worker failed internally",
            extra={"context": {"model_call_id": str(call_id)}},
        )
        return fail_internal_model_call(call_id=call_id)


@shared_task(name="geo.dispatch_model_calls")
def dispatch_model_calls_task():
    timed_out = expire_queue_timeouts()
    stale = expire_stale_running_calls()
    ids = due_model_call_ids(limit=settings.GEO_DETECTION_DISPATCH_BATCH)
    correlation_id = str(uuid.uuid4())
    for call_id in ids:
        execute_model_call_task.apply_async(
            args=[str(call_id)],
            queue="geo_detection",
            headers={"request_id": str(uuid.uuid4()), "correlation_id": correlation_id},
        )
    return {"queued": len(ids), "queue_timeouts": timed_out, "stale_failed": stale}
