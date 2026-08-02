from django.apps import AppConfig


class QuotasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.quotas"

    def ready(self) -> None:
        from . import checks  # noqa: F401
