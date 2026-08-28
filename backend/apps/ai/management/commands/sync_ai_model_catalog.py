from django.core.management.base import BaseCommand
from django.db import transaction

from ...catalog import BUILTIN_AI_MODELS, BUILTIN_PROVIDER_KEYS
from ...models import AIModel, AIModelRuntimeConfig, AIProvider


class Command(BaseCommand):
    help = "检查或幂等修复固定 8 模型目录；默认 dry-run。"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="实际写入；默认 dry-run。")

    @transaction.atomic
    def handle(self, *args, **options):
        apply_changes = options["apply"]
        changes = 0
        expected_model_keys = {item.model_key for item in BUILTIN_AI_MODELS}
        expected_provider_keys = set(BUILTIN_PROVIDER_KEYS)
        unexpected_models = AIModel.objects.exclude(model_key__in=expected_model_keys).count()
        unexpected_providers = AIProvider.objects.exclude(
            provider_key__in=expected_provider_keys
        ).count()
        changes += unexpected_models + unexpected_providers

        for item in BUILTIN_AI_MODELS:
            provider = AIProvider.objects.filter(provider_key=item.provider_key).first()
            if provider is None:
                changes += 1
                if apply_changes:
                    provider = AIProvider.objects.create(
                        provider_key=item.provider_key,
                        canonical_name=item.provider_name,
                        is_builtin=True,
                    )
            elif provider.canonical_name != item.provider_name or not provider.is_builtin:
                changes += 1

            model = AIModel.objects.filter(model_key=item.model_key).first()
            if model is None:
                changes += 1
                if apply_changes and provider is not None:
                    model = AIModel.objects.create(
                        provider=provider,
                        model_key=item.model_key,
                        canonical_display_name=item.display_name,
                        canonical_order=item.canonical_order,
                        purpose=AIModel.Purpose.GEO_DETECTION,
                        is_builtin=True,
                    )
            elif (
                provider is None
                or model.provider_id != provider.id
                or model.canonical_display_name != item.display_name
                or model.canonical_order != item.canonical_order
                or model.purpose != AIModel.Purpose.GEO_DETECTION
                or not model.is_builtin
            ):
                changes += 1

            if model is not None and not AIModelRuntimeConfig.objects.filter(model=model).exists():
                changes += 1
                if apply_changes:
                    AIModelRuntimeConfig.objects.create(
                        model=model, sort_order=item.canonical_order
                    )

        if unexpected_models or unexpected_providers:
            self.stdout.write(
                self.style.WARNING("发现固定目录之外的 provider/model；不会自动删除。")
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"{'已应用' if apply_changes else 'dry-run'}：发现 {changes} 项需要同步。"
            )
        )
        if not apply_changes:
            transaction.set_rollback(True)
