import os

from celery import Celery  # type: ignore[import-untyped]  # Celery does not publish py.typed.

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("xianwen_geo")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
