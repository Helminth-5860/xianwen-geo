from __future__ import annotations

from datetime import timedelta

from celery import shared_task  # type: ignore[import-untyped]
from django.utils import timezone

from .execution import execute_target, prepare_publication


@shared_task(name="publishing.prepare_publication", bind=True, ignore_result=True)
def prepare_publication_task(self, publication_id: str):
    result = prepare_publication(publication_id=publication_id)
    if result.get("status") == "waiting":
        self.apply_async(
            args=[publication_id],
            countdown=max(2, min(30, int(result.get("retry_after") or 4))),
        )
        return None
    if result.get("status") == "ready":
        from .models import PublicationTarget

        targets = list(
            PublicationTarget.objects.filter(
                publication_id=publication_id,
                status=PublicationTarget.Status.READY,
            )
            .only("id", "scheduled_at", "platform_key")
            .order_by("scheduled_at", "platform_key", "id")
        )
        start = timezone.now()
        for index, target in enumerate(targets):
            eta = target.scheduled_at
            if eta is None:
                # 默认错峰发布，避免同一秒向所有平台同时提交。第一站立即执行，
                # 后续平台按 35 分钟间隔排开；用户明确设置计划时间时尊重原计划。
                eta = start + timedelta(minutes=35 * index)
                PublicationTarget.objects.filter(pk=target.pk).update(scheduled_at=eta)
            execute_publication_target_task.apply_async(args=[str(target.pk)], eta=eta)
    return None


@shared_task(name="publishing.execute_target", bind=True, ignore_result=True)
def execute_publication_target_task(self, target_id: str):
    result = execute_target(target_id=target_id)
    if result.get("status") == "scheduled" and result.get("eta") is not None:
        self.apply_async(args=[target_id], eta=result["eta"])
    elif result.get("status") == "retry":
        self.apply_async(
            args=[target_id],
            countdown=max(30, min(900, int(result.get("retry_after") or 75))),
        )
    return None
