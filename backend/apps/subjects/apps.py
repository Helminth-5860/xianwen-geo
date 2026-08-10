from django.apps import AppConfig


class SubjectsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.subjects"

    def ready(self):
        from . import checks  # noqa: F401
