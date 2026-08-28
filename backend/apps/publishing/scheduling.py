from __future__ import annotations

from datetime import datetime, time, timedelta

from django.db import transaction
from django.utils import timezone

from .models import Publication, PublishingPreference


_DAY_START = time(9, 30)
_DAY_END = time(20, 30)
_PLATFORM_GAP_MINUTES = 35


def _localize(day, clock: time):
    tz = timezone.get_current_timezone()
    return timezone.make_aware(datetime.combine(day, clock), timezone=tz)


def _next_day_start(value):
    local = timezone.localtime(value)
    return _localize(local.date() + timedelta(days=1), _DAY_START)


def _fit_window(start, platform_count: int):
    local = timezone.localtime(start)
    if local.time() < _DAY_START:
        start = _localize(local.date(), _DAY_START)
        local = timezone.localtime(start)
    if local.time() > _DAY_END:
        start = _next_day_start(start)
        local = timezone.localtime(start)
    span = timedelta(minutes=max(0, platform_count - 1) * _PLATFORM_GAP_MINUTES)
    if timezone.localtime(start + span).date() != local.date() or timezone.localtime(start + span).time() > _DAY_END:
        start = _next_day_start(start)
    return start


def _article_interval(preference: PublishingPreference, platform_count: int) -> timedelta:
    # 同一篇文章的平台错峰本身会占用时间；下一篇至少等这轮分发完成附近再开始。
    platform_span = timedelta(minutes=max(0, platform_count - 1) * _PLATFORM_GAP_MINUTES + 45)
    if preference.frequency_mode == PublishingPreference.FrequencyMode.FIXED:
        daily_interval = timedelta(hours=max(2.0, 11.0 / max(1, preference.posts_per_day)))
    else:
        daily_interval = timedelta(hours=6)
    return max(platform_span, daily_interval)


@transaction.atomic
def assign_publication_schedule(publication_id):
    publication = Publication.objects.select_for_update().select_related("subject").get(pk=publication_id)
    if publication.scheduled_at is not None:
        return publication.scheduled_at

    preference = PublishingPreference.objects.select_for_update().get(subject=publication.subject)
    now = timezone.now() + timedelta(minutes=2)
    platform_count = max(1, len(publication.platform_plan or []))
    latest = (
        Publication.objects.filter(
            subject=publication.subject,
            scheduled_at__isnull=False,
        )
        .exclude(pk=publication.pk)
        .exclude(status__in=(Publication.Status.CANCELLED, Publication.Status.FAILED))
        .order_by("-scheduled_at")
        .first()
    )
    if latest is None:
        proposed = now
    else:
        previous_count = max(1, len(latest.platform_plan or []))
        proposed = max(now, latest.scheduled_at + _article_interval(preference, previous_count))

    scheduled = _fit_window(proposed, platform_count)
    publication.scheduled_at = scheduled
    publication.save(update_fields=("scheduled_at", "updated_at"))
    return scheduled
