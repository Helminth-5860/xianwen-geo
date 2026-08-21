from __future__ import annotations

import re
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from ...models import ReleaseEvidence

KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,99}$")


class Command(BaseCommand):
    help = "Append safe metadata after a real external gate; never performs the gate itself."

    def add_arguments(self, parser):
        parser.add_argument("evidence_key")
        parser.add_argument("--deploy-sha", required=True)
        parser.add_argument("--safe-code", default="PASSED")
        parser.add_argument("--model", default="")
        parser.add_argument("--provider-request-id", default="")
        parser.add_argument("--latency-ms", type=int)
        parser.add_argument("--degraded", action="store_true")
        parser.add_argument("--expires-in-hours", type=int, default=24)

    def handle(self, *args, **options):
        evidence_key = options["evidence_key"].strip().lower()
        deploy_sha = options["deploy_sha"].strip().lower()
        safe_code = options["safe_code"].strip().upper()
        if not KEY_PATTERN.fullmatch(evidence_key):
            raise CommandError("Evidence key must be a stable lowercase machine key.")
        if evidence_key not in settings.RELEASE_EXPECTED_EXTERNAL_EVIDENCE:
            raise CommandError("Evidence key is not part of the frozen release gate.")
        if len(deploy_sha) != 40 or any(char not in "0123456789abcdef" for char in deploy_sha):
            raise CommandError("Deploy SHA must be 40 lowercase hexadecimal characters.")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,99}", safe_code):
            raise CommandError("Safe code is invalid.")
        if options["expires_in_hours"] < 1 or options["expires_in_hours"] > 168:
            raise CommandError("Evidence expiry must be between 1 and 168 hours.")
        if options["latency_ms"] is not None and options["latency_ms"] < 0:
            raise CommandError("Latency must be non-negative.")
        for value_name in ("model", "provider_request_id"):
            value = options[value_name]
            if len(value) > 255 or any(ord(char) < 32 for char in value):
                raise CommandError(f"{value_name} is invalid.")

        now = timezone.now()
        row = ReleaseEvidence.objects.create(
            environment=settings.API_CREDENTIAL_ENVIRONMENT,
            evidence_key=evidence_key,
            deploy_sha=deploy_sha,
            observed_at=now,
            expires_at=now + timedelta(hours=options["expires_in_hours"]),
            safe_summary={
                "code": safe_code,
                "model": options["model"],
                "provider_request_id": options["provider_request_id"],
                "latency_ms": options["latency_ms"],
                "degraded": options["degraded"],
            },
        )
        self.stdout.write(f"RELEASE_EVIDENCE_RECORDED id={row.pk} key={evidence_key} expires=true")
