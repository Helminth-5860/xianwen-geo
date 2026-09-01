from django.core.management.base import BaseCommand
from django.db import transaction

from apps.plans.models import Subscription
from apps.plans.subscription_services import (
    ensure_default_free_subscription,
    terminate_internal_test_subscription,
)
from apps.users.models import User


class Command(BaseCommand):
    help = "为普通客户补齐注册即享的免费套餐，并停用旧内部测试授权。"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="应用套餐补齐。")

    def handle(self, *args, **options):
        customers = User.objects.filter(
            is_active=True,
            account_status=User.AccountStatus.ACTIVE,
            is_staff=False,
            is_superuser=False,
        ).order_by("created_at", "id")
        if not options["apply"]:
            self.stdout.write(
                f"将检查 {customers.count()} 个普通客户；使用 --apply 后才会写入。"
            )
            return

        granted = 0
        normalized = 0
        unchanged = 0
        for customer_id in customers.values_list("id", flat=True):
            with transaction.atomic():
                customer = User.objects.select_for_update().get(pk=customer_id)
                if customer.is_test_account:
                    terminate_internal_test_subscription(user=customer)
                    customer.is_test_account = False
                    customer.save(update_fields=("is_test_account", "updated_at"))
                    normalized += 1
                has_active = Subscription.objects.filter(
                    user=customer,
                    status=Subscription.Status.ACTIVE,
                ).exists()
                if has_active:
                    unchanged += 1
                    continue
                ensure_default_free_subscription(user=customer)
                granted += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"已补齐免费套餐 {granted} 个，已停用旧测试授权 {normalized} 个，"
                f"已有正式套餐 {unchanged} 个。"
            )
        )
