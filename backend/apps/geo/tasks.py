from __future__ import annotations

import logging
import uuid

from celery import shared_task  # type: ignore[import-untyped]
from django.conf import settings
from django.db import InterfaceError, OperationalError

from .models import ModelCall
from .reports import prepare_report
from .score_orchestration import score_model_response
from .services import (
    due_model_call_ids,
    execute_model_call,
    expire_queue_timeouts,
    expire_stale_running_calls,
    fail_internal_model_call,
)

logger = logging.getLogger("xianwen.geo")


@shared_task(name="geo.execute_strategy_report")
def execute_strategy_report_task(strategy_id):
    from .strategy import execute_strategy_report

    return execute_strategy_report(strategy_id=strategy_id)


@shared_task(name="geo.execute_report_export")
def execute_report_export_task(export_id):
    from .reports import execute_export

    result = execute_export(export_id=export_id)
    return {"status": result.status}


@shared_task(name="geo.prepare_report")
def prepare_report_task(job_id):
    from .models import GeoDetectionJob

    job = GeoDetectionJob.objects.get(pk=job_id)
    report = prepare_report(job=job)
    return {"status": "ready" if report is not None else "pending"}


@shared_task(bind=True, name="geo.execute_semantic_score")
def execute_semantic_score_task(self, model_response_id):
    try:
        result = score_model_response(model_response_id=model_response_id)
        if result is not None:
            prepare_report_task.apply_async(
                args=[str(result.model_response.model_call.job_id)], queue="system_tasks"
            )
        return {"status": "scored" if result is not None else "not_applicable"}
    except Exception as exc:
        if self.request.retries >= settings.GEO_DETECTION_INTERNAL_MAX_RETRIES:
            logger.exception(
                "geo semantic scoring exhausted retries",
                extra={"context": {"model_response_id": str(model_response_id)}},
            )
            return {"status": "failed"}
        raise self.retry(
            args=[str(model_response_id)],
            exc=exc,
            countdown=min(60, 2 ** (self.request.retries + 1)),
            max_retries=settings.GEO_DETECTION_INTERNAL_MAX_RETRIES,
        ) from exc


@shared_task(bind=True, name="geo.execute_model_call")
def execute_model_call_task(self, call_id):
    try:
        result = execute_model_call(call_id=call_id)
        if result.get("status") in {"succeeded", "failed", "cancelled"}:
            call = ModelCall.objects.select_related("response").filter(pk=call_id).first()
            if (
                call is not None
                and result["status"] == "succeeded"
                and call.question_snapshot.participates_in_scoring
            ):
                execute_semantic_score_task.apply_async(
                    args=[str(call.response.pk)], queue="system_tasks"
                )
            elif call is not None:
                prepare_report_task.apply_async(args=[str(call.job_id)], queue="system_tasks")
        return result
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
