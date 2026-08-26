from contextlib import nullcontext
from types import SimpleNamespace

from apps.website_audits import semantic_services


class _FakeQuery:
    def __init__(self, audit):
        self.audit = audit
        self.locked = False
        self.get_kwargs = None

    def select_for_update(self):
        self.locked = True
        return self

    def select_related(self, *args, **kwargs):
        raise AssertionError("nullable related rows must not be joined into FOR UPDATE")

    def get(self, **kwargs):
        assert self.locked is True
        self.get_kwargs = kwargs
        return self.audit


class _Status:
    SUCCEEDED = "succeeded"


class _SemanticStatus:
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


def test_start_semantic_audit_locks_only_audit_row(monkeypatch):
    saved = []
    audit = SimpleNamespace(
        status=_Status.SUCCEEDED,
        semantic_status=_SemanticStatus.FAILED,
        semantic_started_at=None,
        semantic_finished_at=None,
        semantic_error_code="previous_error",
    )
    audit.save = lambda *, update_fields: saved.append(tuple(update_fields))
    query = _FakeQuery(audit)

    fake_model = SimpleNamespace(
        objects=query,
        Status=_Status,
        SemanticStatus=_SemanticStatus,
    )
    monkeypatch.setattr(semantic_services, "WebsiteAudit", fake_model)
    monkeypatch.setattr(semantic_services.transaction, "atomic", lambda: nullcontext())

    result = semantic_services._start_semantic_audit("audit-id")

    assert result is audit
    assert query.get_kwargs == {"pk": "audit-id"}
    assert audit.semantic_status == _SemanticStatus.RUNNING
    assert audit.semantic_finished_at is None
    assert audit.semantic_error_code == ""
    assert saved == [
        (
            "semantic_status",
            "semantic_started_at",
            "semantic_finished_at",
            "semantic_error_code",
            "updated_at",
        )
    ]
