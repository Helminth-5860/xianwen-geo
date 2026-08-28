import os

from celery import Celery  # type: ignore[import-untyped]  # Celery does not publish py.typed.

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("xianwen_geo")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# 恢复因服务重启或瞬时队列故障而中断的自动发文任务。任务本身幂等，
# 这里只做低频兜底扫描，不负责正常发布调度。
app.conf.beat_schedule = {
    **(app.conf.beat_schedule or {}),
    "publishing-recover-interrupted": {
        "task": "publishing.recover_interrupted",
        "schedule": 300.0,
    },
}
