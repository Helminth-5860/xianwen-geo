from django.core.management.base import BaseCommand

from ...models import SubjectVersion
from ...risk_services import assess_existing_subject_versions, published_catalog_revision


class Command(BaseCommand):
    help = "使用一个固定的已发布风险目录修订评估尚无 Assessment 的既有主体版本。"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="写入不可变评估事实。")

    def handle(self, *args, **options):
        revision = published_catalog_revision()
        pending = SubjectVersion.objects.filter(risk_assessment__isnull=True).count()
        if not options["apply"]:
            self.stdout.write(
                f"待评估版本：{pending}；固定目录修订：{revision.id}。使用 --apply 执行。"
            )
            return
        result = assess_existing_subject_versions()
        self.stdout.write(
            self.style.SUCCESS(
                (
                    "评估完成：revision={revision_id} assessed={assessed} reviews={reviews_created}"
                ).format(**result)
            )
        )
