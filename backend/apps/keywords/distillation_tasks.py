import uuid

from celery import shared_task  # type: ignore[import-untyped]
from django.conf import settings
from django.db import InterfaceError, OperationalError

from .distillation_exceptions import DistillationUnexpectedError
from .distillation_services import (
    due_distillation_job_ids,
    execute_distillation,
    fail_internal_distillation,
)


@shared_task(bind=True, name="keywords.execute_distillation")
def execute_distillation_task(self, job_id, generation=None):
    try:
        return execute_distillation(job_id=job_id, expected_generation=generation)
    except DistillationUnexpectedError as exc:
        maximum = settings.DISTILLATION_INTERNAL_MAX_RETRIES
        if self.request.retries >= maximum:
            return fail_internal_distillation(job_id=exc.job_id, generation=exc.generation)
        raise self.retry(
            args=[str(exc.job_id), str(exc.generation)],
            countdown=min(300, 2 ** (self.request.retries + 1)),
            max_retries=maximum,
        ) from exc
    except (OperationalError, InterfaceError) as exc:
        raise self.retry(
            exc=exc,
            countdown=min(300, 2 ** (self.request.retries + 1)),
            max_retries=settings.DISTILLATION_INTERNAL_MAX_RETRIES,
        ) from exc


@shared_task(name="keywords.dispatch_distillation_jobs")
def dispatch_distillation_jobs():
    ids = due_distillation_job_ids()
    correlation_id = str(uuid.uuid4())
    for job_id in ids:
        execute_distillation_task.apply_async(
            args=[str(job_id)],
            queue="ai_content",
            headers={"request_id": str(uuid.uuid4()), "correlation_id": correlation_id},
        )
    return {"queued": len(ids)}
