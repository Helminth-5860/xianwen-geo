from __future__ import annotations

import logging

from celery import shared_task  # type: ignore[import-untyped]
from django.db.models import Q
from django.utils import timezone

from .models import VideoGenerationJob
from .services import execute_video_job

logger = logging.getLogger(__name__)


@shared_task(
    name="videos.execute_generation",
    bind=True,
    ignore_result=True,
    soft_time_limit=300,
    time_limit=330,
)
def execute_video_job_task(self, job_id: str):
    result = execute_video_job(job_id=job_id)
    if result.get("status") in {"continue", "waiting", "busy"}:
        self.apply_async(
            args=[job_id],
            countdown=max(0, int(result.get("retry_after", 0))),
            queue="image_generation",
        )
    return None


@shared_task(name="videos.dispatch_due_jobs", ignore_result=True)
def dispatch_due_video_jobs_task():
    now = timezone.now()
    job_ids = list(
        VideoGenerationJob.objects.filter(
            status__in=(
                VideoGenerationJob.Status.QUEUED,
                VideoGenerationJob.Status.PROCESSING,
            )
        )
        .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
        .filter(Q(lease_expires_at__isnull=True) | Q(lease_expires_at__lte=now))
        .order_by("created_at")
        .values_list("pk", flat=True)[:100]
    )
    for job_id in job_ids:
        execute_video_job_task.apply_async(
            args=[str(job_id)],
            queue="image_generation",
        )
    return len(job_ids)
