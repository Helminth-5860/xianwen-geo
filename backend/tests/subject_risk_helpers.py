import uuid

from django.core.management import call_command

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
    snapshot = {"format_version": 1, "risk_types": [], "rules": []}
    draft_digest = catalog_digest(snapshot)
    revision = SubjectRiskCatalogRevision.objects.create(
        revision_no=1,
        draft_version=1,
        snapshot=snapshot,
        snapshot_digest=draft_digest,
        published_by=requester,
    )
    SubjectRiskCatalogState.objects.update_or_create(
        pk=1,
        defaults={"version": 2, "published_revision": revision},
    )
    return revision
