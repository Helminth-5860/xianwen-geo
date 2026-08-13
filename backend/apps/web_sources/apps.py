from django.apps import AppConfig


class WebSourcesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.web_sources"

    def ready(self) -> None:
        from . import checks  # noqa: F401
