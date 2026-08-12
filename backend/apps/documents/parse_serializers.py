from rest_framework import serializers

from apps.admin_rbac.serializers import StrictSerializer

from .parse_models import DocumentParseJob


class ParseRequestSerializer(StrictSerializer):
    document_version_id = serializers.UUIDField()


class ConfirmParseSerializer(StrictSerializer):
    expected_parse_state_version = serializers.IntegerField(min_value=1)
    source_parsed_version_id = serializers.UUIDField()
    confirmed_text = serializers.CharField(allow_blank=True, trim_whitespace=False)


class ParseJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentParseJob
        fields = ("id", "status", "stable_error_code", "created_at", "updated_at")


def serialize_parse_result(*, job, state):
    latest = state.latest_parsed_version if state is not None else None
    confirmed = state.current_confirmed_version if state is not None else None
    machine = None
    if latest is not None:
        machine = latest if latest.source == "parser" else latest.machine_base_version
    return {
        "status": job.status if job is not None else "not_started",
        "stable_error_code": job.stable_error_code if job is not None else "",
        "state_version": state.version if state is not None else None,
        "latest_version": (
            {"id": str(latest.pk), "version_no": latest.version_no} if latest is not None else None
        ),
        "current_confirmed_version": (
            {"id": str(confirmed.pk), "version_no": confirmed.version_no}
            if confirmed is not None
            else None
        ),
        "canonical_text": latest.extracted_text if latest is not None else "",
        "tables": machine.tables_json if machine is not None else [],
        "warning_codes": machine.warning_codes if machine is not None else [],
        "confirmed": confirmed is not None and latest is not None and confirmed.pk == latest.pk,
        "parser": (
            {
                "key": machine.parser_key,
                "version": machine.parser_version,
                "ocr_engine_version": machine.ocr_engine_version,
            }
            if machine is not None
            else None
        ),
    }
