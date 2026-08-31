from django.apps import AppConfig


class AdminRbacConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.admin_rbac"

    def ready(self) -> None:
        from . import checks, sensitive_audit_models, signals  # noqa: F401
