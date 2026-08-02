from django.core.management.base import BaseCommand, CommandError

from apps.quotas.exceptions import QuotaStateConflict
from apps.quotas.services import verify_all_accounts


class Command(BaseCommand):
    help = "严格按账户 sequence 重放额度流水并验证最终余额。"

    def handle(self, *args, **options):
        try:
            results = verify_all_accounts()
        except QuotaStateConflict as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"额度流水校验通过：{len(results)} 个账户。"))
