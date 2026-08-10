from django.core.management.base import BaseCommand, CommandError

from ...catalog_services import CatalogSemanticDrift, synchronize_subject_catalog


class Command(BaseCommand):
    help = "验证或同步内置主体类型与公共字段目录。"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="创建缺失目录记录。")

    def handle(self, *args, **options):
        try:
            changes = synchronize_subject_catalog(apply_changes=options["apply"])
        except CatalogSemanticDrift as exc:
            raise CommandError(str(exc)) from exc
        if changes and not options["apply"]:
            raise CommandError(f"主体目录存在 {changes} 项缺失。")
        self.stdout.write(self.style.SUCCESS(f"主体目录检查完成，变更项：{changes}"))
