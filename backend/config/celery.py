import os

from celery import Celery  # type: ignore[import-untyped]  # Celery does not publish py.typed.

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("xianwen_geo")
app.config_from_object("django.conf:settings", namespace="CELERY")

# 平台发布本身可能需要等待第三方编辑器/审核接口响应，不能继承全局 60 秒硬时限。
# Worker HTTP 最大允许 300 秒；任务时限必须更长，才能让 worker_client 在超时时把
# 结果安全地标记为“待确认”，而不是被 Celery 先强杀后产生重复发布风险。
app.conf.task_annotations = {
    **dict(app.conf.task_annotations or {}),
    "publishing.execute_target": {
        "soft_time_limit": 330,
        "time_limit": 360,
    },
    "publishing.check_submitted_target": {
        "soft_time_limit": 210,
        "time_limit": 240,
    },
}

app.autodiscover_tasks()

# 恢复因服务重启或瞬时队列故障而中断的自动发文任务。准备类任务可以安全补发；
# 已进入真实平台发布动作的 RUNNING 任务不会自动重放，而由恢复任务转为“结果待确认”。
app.conf.beat_schedule = {
    **(app.conf.beat_schedule or {}),
    "publishing-recover-interrupted": {
        "task": "publishing.recover_interrupted",
        "schedule": 300.0,
    },
}
