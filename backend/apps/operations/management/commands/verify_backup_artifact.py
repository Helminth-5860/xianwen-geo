from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from ...models import BackupRecord


class Command(BaseCommand):
    help = "Verify an existing backup checksum and pg_restore catalog; never creates a backup."

    def add_arguments(self, parser):
        parser.add_argument("artifact", type=Path)
        parser.add_argument("--expected-sha256", required=True)
        parser.add_argument("--location-reference", required=True)
        parser.add_argument("--scope", default="postgresql")
        parser.add_argument("--pg-restore", default="pg_restore")
        parser.add_argument("--encrypted", action="store_true")

    def handle(self, *args, **options):
        artifact = options["artifact"].resolve(strict=True)
        expected = options["expected_sha256"].strip().lower()
        if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
            raise CommandError("Expected SHA-256 must be 64 lowercase hexadecimal characters.")
        digest = hashlib.sha256()
        with artifact.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        actual = digest.hexdigest()
        if actual != expected:
            raise CommandError("Backup checksum mismatch.")
        result = subprocess.run(
            [options["pg_restore"], "--list", str(artifact)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if result.returncode != 0:
            raise CommandError("pg_restore catalog verification failed.")
        row = BackupRecord.objects.create(
            kind="postgresql_custom",
            scope=options["scope"],
            location_reference=options["location_reference"],
            encrypted=options["encrypted"],
            status=BackupRecord.Status.VERIFIED,
            checksum_sha256=actual,
            restore_verified_at=None,
        )
        self.stdout.write(
            f"BACKUP_ARTIFACT_VERIFIED record_id={row.pk} checksum_present=true "
            "catalog=valid restore_verified=false"
        )
