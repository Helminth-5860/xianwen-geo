import uuid

from django.core.management.base import BaseCommand, CommandError

from apps.plans.models import Subscription
from apps.quotas.services import reconcile_storage_capacity_for_user


class Command(BaseCommand):
    help = "Reconcile active storage capacity from immutable file allocations."

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--dry-run", action="store_true")
        mode.add_argument("--apply", action="store_true")
        parser.add_argument("--batch-size", type=int, default=100)

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        if batch_size < 1 or batch_size > 1000:
            raise CommandError("batch-size must be between 1 and 1000")
        user_ids = (
            Subscription.objects.filter(status=Subscription.Status.ACTIVE)
            .order_by("user_id")
            .values_list("user_id", flat=True)
            .distinct()
        )
        processed = changed = 0
        for user_id in user_ids.iterator(chunk_size=batch_size):
            result = reconcile_storage_capacity_for_user(
                user_id=user_id,
                request_id=uuid.uuid4(),
                apply=options["apply"],
            )
            if result is None:
                continue
            processed += 1
            if result["current"] != result["target"]:
                changed += 1
            self.stdout.write(
                "user={user_id} usage={usage} current={current} target={target}".format(**result)
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"mode={'apply' if options['apply'] else 'dry-run'} "
                f"processed={processed} changed={changed}"
            )
        )
