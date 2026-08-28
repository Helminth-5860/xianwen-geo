from __future__ import annotations

from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from apps.articles.models import ChannelAdaptation
from apps.articles.tasks import execute_generation_job_task
from apps.images.models import ImageGenerationJob
from apps.images.tasks import execute_image_job_task

from .models import Publication


def _claim(kind: str, job_id: str, seconds: int = 60) -> bool:
    return bool(cache.add(f"publishing:recovery:{kind}:{job_id}", "1", timeout=seconds))


def recover_preparation_jobs(publication_id) -> None:
    try:
        publication = Publication.objects.prefetch_related("targets").get(pk=publication_id)
    except Publication.DoesNotExist:
        return
    if publication.status not in {Publication.Status.PREPARING, Publication.Status.QUEUED}:
        return

    image_ids = [str(item) for item in (publication.image_plan or {}).get("supplement_job_ids") or []]
    cutoff = timezone.now() - timedelta(seconds=20)
    for job in ImageGenerationJob.objects.filter(
        pk__in=image_ids,
        status=ImageGenerationJob.Status.QUEUED,
        started_at__isnull=True,
        created_at__lte=cutoff,
    ):
        if _claim("image", str(job.pk)):
            execute_image_job_task.delay(str(job.pk))

    platform_keys = [target.platform_key for target in publication.targets.all()]
    adaptations = (
        ChannelAdaptation.objects.filter(
            article_id=publication.article_id,
            channel__key__in=platform_keys,
            status=ChannelAdaptation.Status.QUEUED,
            job__status="queued",
            job__started_at__isnull=True,
            job__created_at__lte=cutoff,
        )
        .select_related("job")
        .order_by("-created_at")
    )
    seen: set[str] = set()
    for adaptation in adaptations:
        job_id = str(adaptation.job_id)
        if job_id in seen:
            continue
        seen.add(job_id)
        if _claim("adaptation", job_id):
            execute_generation_job_task.delay(job_id)
