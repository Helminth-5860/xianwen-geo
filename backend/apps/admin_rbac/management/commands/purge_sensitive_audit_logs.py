from django.core.management.base import BaseCommand, CommandError

from apps.admin_rbac.sensitive_audit_services import (
    DEFAULT_PURGE_BATCH_SIZE,
    DEFAULT_PURGE_MAX_BATCHES,
    RETENTION_DAYS,
    purge_expired_sensitive_audit_logs,
)


class Command(BaseCommand):
    help = f"分批清理超过 {RETENTION_DAYS} 天的敏感审计日志。"

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=DEFAULT_PURGE_BATCH_SIZE)
        parser.add_argument("--max-batches", type=int, default=DEFAULT_PURGE_MAX_BATCHES)

    def handle(self, *args, **options):
        try:
            deleted = purge_expired_sensitive_audit_logs(
                batch_size=options["batch_size"],
                max_batches=options["max_batches"],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"已清理 {deleted} 条过期敏感审计日志。"))
