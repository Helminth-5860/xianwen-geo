from importlib import import_module

from django.apps import AppConfig


class PublicationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.publications"
    verbose_name = "自动发文"

    def ready(self):
        import_module("apps.publications.managed_tasks")
