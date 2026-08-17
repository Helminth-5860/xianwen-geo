from django.apps import AppConfig


class AIConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ai"
    verbose_name = "AI 模型配置"

    def ready(self) -> None:
        from .adapters import register_real_detection_adapters

        register_real_detection_adapters()
