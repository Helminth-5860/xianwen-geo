from django.core.management.base import BaseCommand, CommandError

from ...catalog_services import CatalogSemanticDrift, synchronize_plan_catalog


class Command(BaseCommand):
    help = "检查或同步代码拥有的套餐限制键目录。"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="应用非破坏性目录同步。")

    def handle(self, *args, **options):
        try:
            changes = synchronize_plan_catalog(apply_changes=options["apply"])
        except CatalogSemanticDrift as exc:
            raise CommandError(str(exc)) from exc
        if changes and not options["apply"]:
            raise CommandError(f"检测到 {changes} 项套餐限制键目录漂移。")
        if changes:
            self.stdout.write(self.style.SUCCESS(f"已同步 {changes} 项套餐限制键。"))
        else:
            self.stdout.write(self.style.SUCCESS("套餐限制键目录无漂移。"))
