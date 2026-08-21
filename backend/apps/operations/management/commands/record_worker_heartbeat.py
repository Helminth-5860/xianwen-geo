from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = "Record a bounded worker-queue heartbeat for release readiness."

    def add_arguments(self, parser):
        parser.add_argument(
            "--queue", required=True, choices=settings.RELEASE_EXPECTED_WORKER_QUEUES
        )
        parser.add_argument("--ttl", type=int, default=120)

    def handle(self, *args, **options):
        ttl = options["ttl"]
        if ttl < 30 or ttl > 600:
            raise CommandError("Heartbeat TTL must be between 30 and 600 seconds.")
        queue = options["queue"]
        cache.set(
            f"worker-heartbeat:{queue}",
            {"queue": queue, "observed_at": timezone.now().isoformat()},
            timeout=ttl,
        )
        self.stdout.write(f"WORKER_HEARTBEAT_RECORDED queue={queue} ttl={ttl}")
