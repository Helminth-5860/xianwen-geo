import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from ...readiness import release_readiness_report


class Command(BaseCommand):
    help = "Emit the fail-closed Stage 3 release-readiness report without secrets."

    def handle(self, *args, **options):
        report = release_readiness_report()
        self.stdout.write(
            json.dumps(report, cls=DjangoJSONEncoder, ensure_ascii=False, sort_keys=True)
        )
        if report["status"] != "READY":
            raise CommandError("Release readiness is NOT_READY.")
