from rest_framework.exceptions import NotFound

from apps.admin_rbac.permissions import AdminContext
from apps.admin_rbac.risk_handlers import HandlerContext, HandlerResult, HandlerSpec
from apps.admin_rbac.risk_serializers import EmptyPayloadSerializer

from .models import SubjectRiskCatalogState
from .risk_services import publish_catalog


def _catalog_version(user, context: AdminContext, target_id, lock):
    if str(target_id) == "00000000-0000-0000-0000-000000000001":
        target_id = "1"
    if str(target_id) != "1":
        raise NotFound
    query = SubjectRiskCatalogState.objects.all()
    if lock:
        query = query.select_for_update()
    state = query.get(pk=1)
    return state.version


def handle_catalog_publish(context: HandlerContext) -> HandlerResult:
    before = {"catalog_version": context.target_version}
    revision = publish_catalog(
        request=context.request,
        expected_version=context.target_version,
        approval_request=context.approval_request,
    )
    after = {
        "catalog_version": context.target_version + 1,
        "revision_id": str(revision.pk),
        "revision_no": revision.revision_no,
    }
    return HandlerResult(before, after, after)


SUBJECT_RISK_HANDLER_REGISTRY = {
    "subject_risk.catalog.publish": handle_catalog_publish,
}

SUBJECT_RISK_HANDLER_SPECS = {
    "subject_risk.catalog.publish": HandlerSpec(
        "subject_risk.catalog.publish",
        False,
        EmptyPayloadSerializer,
        _catalog_version,
        handle_catalog_publish,
    ),
}
