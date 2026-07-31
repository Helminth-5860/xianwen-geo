from celery import shared_task  # type: ignore[import-untyped]


@shared_task(name="system.health_check")
def system_health_check() -> dict[str, str]:
    return {"status": "ok"}
