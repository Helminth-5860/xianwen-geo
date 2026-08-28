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


def _platform_span(platform_count: int) -> timedelta:
    return timedelta(minutes=max(0, platform_count - 1) * _PLATFORM_GAP_MINUTES)


def _fit_window(start, platform_count: int):
    local = timezone.localtime(start)
    if local.time() < _DAY_START:
        start = _localize(local.date(), _DAY_START)
        local = timezone.localtime(start)
    if local.time() > _DAY_END:
        start = _next_day_start(start)
        local = timezone.localtime(start)
    span = _platform_span(platform_count)
    if timezone.localtime(start + span).date() != local.date() or timezone.localtime(start + span).time() > _DAY_END:
        start = _next_day_start(start)
    return start


def _article_interval(preference: PublishingPreference, platform_count: int) -> timedelta:
    # 同一篇文章的平台错峰本身会占用时间；下一篇至少等这轮分发完成附近再开始。
    platform_span = _platform_span(platform_count) + timedelta(minutes=45)
    if preference.frequency_mode == PublishingPreference.FrequencyMode.FIXED:
        daily_interval = timedelta(hours=max(2.0, 11.0 / max(1, preference.posts_per_day)))
    else:
        daily_interval = timedelta(hours=6)
    return max(platform_span, daily_interval)


def _day_bounds(day):
    start = _localize(day, time(0, 0))
    return start, start + timedelta(days=1)


def _fixed_slot(day, index: int, posts_per_day: int, platform_count: int):
    """Return a daily article start slot that leaves room for the platform wave."""
    day_start = _localize(day, _DAY_START)
    day_end = _localize(day, _DAY_END)
    latest_start = day_end - _platform_span(platform_count)
    if latest_start < day_start:
        return None
    count = max(1, posts_per_day)
    if count == 1:
        return day_start
    usable = latest_start - day_start
    step = usable / (count - 1)
    return day_start + step * min(max(0, index), count - 1)


def _fixed_schedule_candidate(*, publication: Publication, preference: PublishingPreference, now, platform_count: int):
    day = timezone.localtime(now).date()
    for _ in range(366):
        start_bound, end_bound = _day_bounds(day)
        existing = list(
            Publication.objects.filter(
                subject=publication.subject,
                scheduled_at__gte=start_bound,
                scheduled_at__lt=end_bound,
            )
            .exclude(pk=publication.pk)
            .exclude(status__in=(Publication.Status.CANCELLED, Publication.Status.FAILED))
            .order_by("scheduled_at")
        )
        if len(existing) >= preference.posts_per_day:
            day += timedelta(days=1)
            continue

        candidate = _fixed_slot(day, len(existing), preference.posts_per_day, platform_count)
        if candidate is None:
            day += timedelta(days=1)
            continue
        candidate = max(candidate, now)

        if existing:
            previous = existing[-1]
            previous_count = max(1, len(previous.platform_plan or []))
            candidate = max(
                candidate,
                previous.scheduled_at + _platform_span(previous_count) + timedelta(minutes=45),
            )

        fitted = _fit_window(candidate, platform_count)
        if timezone.localtime(fitted).date() != day:
            day += timedelta(days=1)
            continue
        return fitted
    # Defensive fallback; impossible under normal 1..10 posts/day validation.
    return _localize(day, _DAY_START)


@transaction.atomic
def assign_publication_schedule(publication_id):
    publication = Publication.objects.select_for_update().select_related("subject").get(pk=publication_id)
    if publication.scheduled_at is not None:
        return publication.scheduled_at

    # Locking the one-per-subject preference serializes concurrent schedule assignment
    # for this subject, preventing two freshly generated articles from taking the same slot.
    preference = PublishingPreference.objects.select_for_update().get(subject=publication.subject)
    now = timezone.now() + timedelta(minutes=2)
    platform_count = max(1, len(publication.platform_plan or []))

    if preference.frequency_mode == PublishingPreference.FrequencyMode.FIXED:
        scheduled = _fixed_schedule_candidate(
            publication=publication,
            preference=preference,
            now=now,
            platform_count=platform_count,
        )
    else:
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
