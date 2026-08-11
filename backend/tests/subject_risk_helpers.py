import uuid
from datetime import timedelta

from django.core.management import call_command
from django.utils import timezone

from apps.admin_rbac.models import ApprovalRequest, RiskAction
from apps.subjects.models import SubjectRiskCatalogRevision, SubjectRiskCatalogState
from apps.subjects.risk_engine import catalog_digest
from apps.users.models import User


def install_empty_published_risk_catalog() -> SubjectRiskCatalogRevision:
    call_command("sync_admin_rbac", "--apply", verbosity=0)
    SubjectRiskCatalogState.objects.get_or_create(pk=1, defaults={"version": 1})
    existing = (
        SubjectRiskCatalogState.objects.select_related("published_revision").filter(pk=1).first()
    )
    if existing is not None and existing.published_revision_id is not None:
        return existing.published_revision
    requester = User.objects.create_superuser(
        phone=f"139{uuid.uuid4().int % 100000000:08d}",
        nickname="Risk catalog test requester",
        password="Test-Risk-Catalog-2026!",
    )
    approver = User.objects.create_superuser(
        phone=f"137{uuid.uuid4().int % 100000000:08d}",
        nickname="Risk catalog test approver",
        password="Test-Risk-Catalog-2026!",
    )
    action = RiskAction.objects.get(pk="subject_risk.catalog.publish")
    snapshot = {"format_version": 1, "risk_types": [], "rules": []}
    draft_digest = catalog_digest(snapshot)
    now = timezone.now()
    approval = ApprovalRequest.objects.create(
        action=action,
        action_key=action.key,
        policy_version=action.policy.version,
        requester=requester,
        target_type=action.target_type,
        target_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        target_version=1,
        sanitized_payload={"draft_digest": draft_digest},
        payload_digest="0" * 64,
        safe_summary="Test-only empty catalog publication.",
        status=ApprovalRequest.Status.EXECUTED,
        expires_at=now + timedelta(days=1),
        approved_by=approver,
        approved_at=now,
        executed_at=now,
        execution_result={"revision_no": 1},
        request_id=uuid.uuid4(),
    )
    revision = SubjectRiskCatalogRevision.objects.create(
        revision_no=1,
        draft_version=1,
        snapshot=snapshot,
        snapshot_digest=draft_digest,
        published_by=approver,
        approval_request=approval,
    )
    SubjectRiskCatalogState.objects.update_or_create(
        pk=1,
        defaults={"version": 2, "published_revision": revision},
    )
    return revision
