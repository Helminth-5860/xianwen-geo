import uuid

from celery import shared_task  # type: ignore[import-untyped]
from django.conf import settings
from django.db import InterfaceError, OperationalError

from .enrichment_exceptions import SubjectEnrichmentUnexpectedError
from .enrichment_services import (
    due_enrichment_job_ids,
    execute_enrichment,
    fail_internal_enrichment,
)


@shared_task(bind=True, name="subjects.execute_enrichment")
def execute_enrichment_task(self, job_id, generation=None):
    try:
        return execute_enrichment(job_id=job_id, expected_generation=generation)
    except SubjectEnrichmentUnexpectedError as exc:
        maximum = settings.SUBJECT_ENRICHMENT_INTERNAL_MAX_RETRIES
        if self.request.retries >= maximum:
            return fail_internal_enrichment(job_id=exc.job_id, generation=exc.generation)
        raise self.retry(
            args=[str(exc.job_id), str(exc.generation)],
            countdown=min(300, 2 ** (self.request.retries + 1)),
            max_retries=maximum,
        ) from exc
    except (OperationalError, InterfaceError) as exc:
        raise self.retry(
            exc=exc,
            countdown=min(300, 2 ** (self.request.retries + 1)),
            max_retries=settings.SUBJECT_ENRICHMENT_INTERNAL_MAX_RETRIES,
        ) from exc


@shared_task(name="subjects.dispatch_enrichment_jobs")
def dispatch_enrichment_jobs():
    ids = due_enrichment_job_ids()
    correlation_id = str(uuid.uuid4())
    for job_id in ids:
        execute_enrichment_task.apply_async(
            args=[str(job_id)],
            queue="ai_content",
            headers={"request_id": str(uuid.uuid4()), "correlation_id": correlation_id},
        )
    return {"queued": len(ids)}
