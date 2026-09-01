import os

from celery import Celery  # type: ignore[import-untyped]  # Celery does not publish py.typed.
from celery.schedules import crontab  # type: ignore[import-untyped]

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

# 敏感审计日志在线保留 365 天；每天低峰期分批清理过期记录，避免大事务删除。
app.conf.beat_schedule = {
    **(app.conf.beat_schedule or {}),
    "admin-sensitive-audit-retention": {
        "task": "admin_rbac.purge_sensitive_audit_logs",
        "schedule": crontab(hour=3, minute=20),
    },
}
