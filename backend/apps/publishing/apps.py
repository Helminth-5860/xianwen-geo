from django.apps import AppConfig


class PublishingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.publishing"
    verbose_name = "自动发文"

    def ready(self):
        from .runtime_config import validate_runtime_configuration

        validate_runtime_configuration()
        from . import signals  # noqa: F401,E402
