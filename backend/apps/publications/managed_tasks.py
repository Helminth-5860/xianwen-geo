from __future__ import annotations

from celery import shared_task  # type: ignore[import-untyped]
from django.utils import timezone

from apps.articles.models import Article

from .models import AutoPublishPolicy, PublicationJob
from .services import PublicationInputError, create_publication_job


def _daily_limit(policy: AutoPublishPolicy) -> int:
    return {
        AutoPublishPolicy.FrequencyMode.SMART: 1,
        AutoPublishPolicy.FrequencyMode.DAILY_1: 1,
        AutoPublishPolicy.FrequencyMode.DAILY_2: 2,
        AutoPublishPolicy.FrequencyMode.DAILY_3: 3,
        AutoPublishPolicy.FrequencyMode.CUSTOM: policy.custom_daily_limit,
    }.get(policy.frequency_mode, 1)


@shared_task(name="publications.scan_managed_articles", ignore_result=True)
def scan_managed_articles_task():
    today = timezone.localdate()
    policies = list(
        AutoPublishPolicy.objects.select_related("user", "subject")
        .filter(
            enabled=True,
            operating_mode__in=(
                AutoPublishPolicy.OperatingMode.MANAGED,
                AutoPublishPolicy.OperatingMode.REVIEW,
            ),
        )
        .order_by("updated_at")[:500]
    )
    created = 0
    for policy in policies:
        limit = _daily_limit(policy)
        used = PublicationJob.objects.filter(
            policy=policy,
            created_at__date=today,
        ).count()
        remaining = max(0, limit - used)
        if remaining == 0:
            continue
        articles = list(
            Article.objects.filter(
                user=policy.user,
                subject=policy.subject,
                status=Article.Status.READY,
                moderation_status=Article.Moderation.PASSED,
                publication_jobs__isnull=True,
            )
            .order_by("updated_at", "created_at")[:remaining]
        )
        for article in articles:
            try:
                _, was_created = create_publication_job(
                    user=policy.user,
                    article_id=article.pk,
                    idempotency_key=f"managed:{article.pk}:v{article.version}",
                    force_review=policy.operating_mode == AutoPublishPolicy.OperatingMode.REVIEW,
                )
            except PublicationInputError:
                continue
            created += int(was_created)
    return {"created": created}
