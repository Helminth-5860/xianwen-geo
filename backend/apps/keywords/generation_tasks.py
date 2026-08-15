import uuid

from celery import shared_task  # type: ignore[import-untyped]
from django.conf import settings
from django.db import InterfaceError, OperationalError

from .generation_exceptions import KeywordGenerationUnexpectedError
from .generation_services import (
    due_keyword_generation_job_ids,
    execute_keyword_generation,
    fail_internal_keyword_generation,
)


@shared_task(bind=True, name="keywords.execute_generation")
def execute_keyword_generation_task(self, job_id, generation=None):
    try:
        return execute_keyword_generation(job_id=job_id, expected_generation=generation)
    except KeywordGenerationUnexpectedError as exc:
        maximum = settings.KEYWORD_GENERATION_INTERNAL_MAX_RETRIES
        if self.request.retries >= maximum:
            return fail_internal_keyword_generation(job_id=exc.job_id, generation=exc.generation)
        raise self.retry(
            args=[str(exc.job_id), str(exc.generation)],
            countdown=min(300, 2 ** (self.request.retries + 1)),
            max_retries=maximum,
        ) from exc
    except (OperationalError, InterfaceError) as exc:
        raise self.retry(
            exc=exc,
            countdown=min(300, 2 ** (self.request.retries + 1)),
            max_retries=settings.KEYWORD_GENERATION_INTERNAL_MAX_RETRIES,
        ) from exc


@shared_task(name="keywords.dispatch_generation_jobs")
def dispatch_keyword_generation_jobs():
    ids = due_keyword_generation_job_ids()
    correlation_id = str(uuid.uuid4())
    for job_id in ids:
        execute_keyword_generation_task.apply_async(
            args=[str(job_id)],
            queue="ai_content",
            headers={"request_id": str(uuid.uuid4()), "correlation_id": correlation_id},
        )
    return {"queued": len(ids)}
