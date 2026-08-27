from __future__ import annotations

import logging
import uuid

from celery import shared_task  # type: ignore[import-untyped]
from django.conf import settings
from django.db import InterfaceError, OperationalError

from apps.ai.errors import AIAdapterError

from .models import ModelCall
from .reports import prepare_report
from .score_aggregation import ScoreAggregationError
from .score_orchestration import ScoreOrchestrationError, score_model_response
from .semaphores import (
    DetectionDispatchLease,
    DetectionDispatchLeaseStore,
    DetectionSemaphoreUnavailable,
)
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
    except AIAdapterError as exc:
        if not exc.retryable:
            logger.exception(
                "geo semantic scoring failed permanently",
                extra={
                    "context": {
                        "model_response_id": str(model_response_id),
                        "error_code": exc.stable_code,
                    }
                },
            )
            return {"status": "failed"}
        return _retry_semantic_score_task(self, model_response_id=model_response_id, exc=exc)
    except (ScoreAggregationError, ScoreOrchestrationError):
        logger.exception(
            "geo semantic scoring contract failed permanently",
            extra={"context": {"model_response_id": str(model_response_id)}},
        )
        return {"status": "failed"}
    except Exception as exc:
        return _retry_semantic_score_task(self, model_response_id=model_response_id, exc=exc)


def _retry_semantic_score_task(task, *, model_response_id, exc):
    if task.request.retries >= settings.GEO_DETECTION_INTERNAL_MAX_RETRIES:
        logger.exception(
            "geo semantic scoring exhausted retries",
            extra={"context": {"model_response_id": str(model_response_id)}},
        )
        return {"status": "failed"}
    raise task.retry(
        args=[str(model_response_id)],
        exc=exc,
        countdown=min(60, 2 ** (task.request.retries + 1)),
        max_retries=settings.GEO_DETECTION_INTERNAL_MAX_RETRIES,
    ) from exc


def _release_dispatch_lease(*, call_id, dispatch_token) -> None:
    if not dispatch_token:
        return
    try:
        DetectionDispatchLeaseStore().release(
            DetectionDispatchLease(
                token=str(dispatch_token),
                key=f"geo:dispatch:model-call:v1:{call_id}",
            )
        )
    except DetectionSemaphoreUnavailable:
        logger.warning(
            "geo detection dispatch lease release failed",
            extra={"context": {"model_call_id": str(call_id)}},
        )


def _enqueue_terminal_followups(*, call_id, result) -> None:
    if result.get("terminal_transition") is not True:
        return
    call = ModelCall.objects.select_related("response").filter(pk=call_id).first()
    if (
        call is not None
        and result["status"] == "succeeded"
        and call.question_snapshot.participates_in_scoring
    ):
        execute_semantic_score_task.apply_async(args=[str(call.response.pk)], queue="system_tasks")
    elif call is not None:
        prepare_report_task.apply_async(args=[str(call.job_id)], queue="system_tasks")


@shared_task(bind=True, name="geo.execute_model_call")
def execute_model_call_task(self, call_id, dispatch_token=None):
    release_dispatch_lease = True
    try:
        result = execute_model_call(call_id=call_id)
        _enqueue_terminal_followups(call_id=call_id, result=result)
        return result
    except (OperationalError, InterfaceError) as exc:
        if self.request.retries >= settings.GEO_DETECTION_INTERNAL_MAX_RETRIES:
            result = fail_internal_model_call(call_id=call_id)
            _enqueue_terminal_followups(call_id=call_id, result=result)
            return result
        release_dispatch_lease = not bool(dispatch_token)
        raise self.retry(
            args=[str(call_id), dispatch_token],
            exc=exc,
            countdown=min(60, 2 ** (self.request.retries + 1)),
            max_retries=settings.GEO_DETECTION_INTERNAL_MAX_RETRIES,
        ) from exc
    except Exception:
        logger.exception(
            "geo detection worker failed internally",
            extra={"context": {"model_call_id": str(call_id)}},
        )
        result = fail_internal_model_call(call_id=call_id)
        _enqueue_terminal_followups(call_id=call_id, result=result)
        return result
    finally:
        if release_dispatch_lease:
            _release_dispatch_lease(call_id=call_id, dispatch_token=dispatch_token)


@shared_task(name="geo.dispatch_model_calls")
def dispatch_model_calls_task():
    timed_out = expire_queue_timeouts()
    stale = expire_stale_running_calls()
    ids = due_model_call_ids(limit=settings.GEO_DETECTION_DISPATCH_BATCH)
    correlation_id = str(uuid.uuid4())
    store = DetectionDispatchLeaseStore()
    lease_seconds = settings.GEO_DETECTION_QUEUE_TIMEOUT_SECONDS + 60
    queued = 0
    deduplicated = 0
    enqueue_failures = 0
    for call_id in ids:
        try:
            lease = store.acquire(call_id=str(call_id), lease_seconds=lease_seconds)
        except DetectionSemaphoreUnavailable:
            logger.exception("geo detection dispatch lease store unavailable")
            break
        if lease is None:
            deduplicated += 1
            continue
        try:
            execute_model_call_task.apply_async(
                args=[str(call_id), lease.token],
                queue="geo_detection",
                headers={"request_id": str(uuid.uuid4()), "correlation_id": correlation_id},
            )
            queued += 1
        except Exception:
            enqueue_failures += 1
            logger.exception(
                "geo detection model call enqueue failed",
                extra={"context": {"model_call_id": str(call_id)}},
            )
            try:
                store.release(lease)
            except DetectionSemaphoreUnavailable:
                logger.warning(
                    "geo detection dispatch lease rollback failed",
                    extra={"context": {"model_call_id": str(call_id)}},
                )
            break
    return {
        "queued": queued,
        "deduplicated": deduplicated,
        "enqueue_failures": enqueue_failures,
        "queue_timeouts": timed_out,
        "stale_failed": stale,
    }
