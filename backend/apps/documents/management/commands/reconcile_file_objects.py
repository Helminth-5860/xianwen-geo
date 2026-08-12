from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.documents.models import DocumentVersion, FileUploadIntent
from apps.documents.storage import storage_provider


class Command(BaseCommand):
    help = "Reconcile bounded database-known cleanup and aged orphan opaque file objects."

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--dry-run", action="store_true")
        mode.add_argument("--apply", action="store_true")
        parser.add_argument("--batch-size", type=int, default=100)
        parser.add_argument(
            "--minimum-age-seconds",
            type=int,
            default=settings.FILE_STAGING_RETENTION_SECONDS,
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        minimum_age = options["minimum_age_seconds"]
        if batch_size < 1 or batch_size > 1000:
            raise CommandError("batch-size must be between 1 and 1000")
        if minimum_age < settings.FILE_UPLOAD_URL_TTL:
            raise CommandError("minimum-age-seconds must not be shorter than upload credential TTL")

        provider = storage_provider()
        cleanup_rows = list(
            FileUploadIntent.objects.filter(staging_cleanup_pending=True)
            .only("id", "staging_key")
            .order_by("updated_at", "id")[:batch_size]
        )
        known_staging = set(FileUploadIntent.objects.values_list("staging_key", flat=True))
        known_final = set(FileUploadIntent.objects.values_list("final_key", flat=True))
        known_final.update(DocumentVersion.objects.values_list("object_key", flat=True))
        cutoff = timezone.now() - timedelta(seconds=minimum_age)

        orphan_keys: list[str] = []
        for prefix, known in (("staging/", known_staging), ("objects/", known_final)):
            remaining = batch_size - len(orphan_keys)
            if remaining <= 0:
                break
            for item in provider.list_system_objects(prefix=prefix, limit=batch_size):
                if item.key not in known and item.last_modified <= cutoff:
                    orphan_keys.append(item.key)
                    if len(orphan_keys) >= batch_size:
                        break

        cleaned = 0
        orphaned = len(orphan_keys)
        if options["apply"]:
            for intent in cleanup_rows:
                provider.delete_temporary_object(intent.staging_key)
                FileUploadIntent.objects.filter(pk=intent.pk).update(staging_cleanup_pending=False)
                cleaned += 1
            for key in orphan_keys:
                provider.delete_temporary_object(key)
                cleaned += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"mode={'apply' if options['apply'] else 'dry-run'} "
                f"known_cleanup={len(cleanup_rows)} orphan_candidates={orphaned} "
                f"cleaned={cleaned}"
            )
        )
