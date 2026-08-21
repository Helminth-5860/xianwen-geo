from __future__ import annotations

import logging

from celery import shared_task  # type: ignore[import-untyped]

from .services import execute_image_job

logger = logging.getLogger(__name__)


@shared_task(name="images.execute_generation", bind=True, ignore_result=True)
def execute_image_job_task(self, job_id: str):
    result = execute_image_job(job_id=job_id)
    if result.get("status") == "retry_wait":
        self.apply_async(args=[job_id], countdown=int(result["retry_after"]))
    return None
