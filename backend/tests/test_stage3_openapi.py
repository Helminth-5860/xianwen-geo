from pathlib import Path

import yaml

OPENAPI_PATH = Path(__file__).resolve().parents[2] / "openapi" / "openapi-v1.yaml"


def specification():
    return yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))


def test_stage3_openapi_registers_all_operations_and_release_paths():
    paths = specification()["paths"]
    expected = {
        "/announcements": {"get"},
        "/feedback": {"get", "post"},
        "/feedback/{feedbackId}": {"get"},
        "/usage-records": {"get"},
        "/support-view-requests/{supportId}/decision": {"post"},
        "/admin/operations/dashboard": {"get"},
        "/admin/operations/customers": {"get"},
        "/admin/operations/exports/customers": {"post"},
        "/admin/operations/customers/{customerId}": {"get", "patch"},
        "/admin/operations/customers/{customerId}/contacts": {"get", "post"},
        "/admin/operations/customers/{customerId}/followups": {"get", "post"},
        "/admin/operations/followups/{followupId}/action": {"post"},
        "/admin/customer-statuses": {"get", "post"},
        "/admin/customer-statuses/{catalogId}": {"patch"},
        "/admin/customer-tags": {"get", "post"},
        "/admin/customer-tags/{catalogId}": {"patch"},
        "/admin/tasks": {"get"},
        "/admin/moderation": {"get"},
        "/admin/moderation/articles/{articleId}/decision": {"post"},
        "/admin/moderation/images/{imageId}/decision": {"post"},
        "/admin/announcements": {"get", "post"},
        "/admin/announcements/{announcementId}/action": {"post"},
        "/admin/feedback": {"get"},
        "/admin/feedback/{feedbackId}/action": {"post"},
        "/admin/users/{customerId}/support-view-request": {"post"},
        "/admin/support-view-sessions/{supportId}/summary": {"get"},
        "/admin/release-readiness": {"get"},
        "/admin/system-alerts": {"get"},
        "/admin/system-alerts/{alertId}/action": {"post"},
        "/admin/backups": {"get"},
        "/admin/retention-jobs": {"get"},
    }
    for path, methods in expected.items():
        assert path in paths
        assert methods.issubset(paths[path])


def test_release_readiness_openapi_is_fail_closed_and_has_no_secret_fields():
    schemas = specification()["components"]["schemas"]
    readiness = schemas["ReleaseReadinessEnvelope"]
    data = readiness["allOf"][1]["properties"]["data"]
    assert data["properties"]["status"]["enum"] == ["READY", "NOT_READY"]
    assert data["properties"]["secrets_included"]["const"] is False
    serialized = str(readiness).lower()
    for forbidden in ("api_key", "secret_key", "authorization", "password", "raw_provider"):
        assert forbidden not in serialized
