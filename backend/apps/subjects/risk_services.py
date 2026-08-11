import copy
import re
import uuid
from dataclasses import dataclass
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.admin_rbac.audit_services import record_audit_event
from apps.admin_rbac.models import ApprovalRequest
from apps.admin_rbac.scopes import scoped_customers
from apps.users.models import Notification, User

from .models import (
    Subject,
    SubjectReview,
    SubjectReviewEvent,
    SubjectRiskAssessment,
    SubjectRiskCatalogRevision,
    SubjectRiskCatalogState,
    SubjectRiskHit,
    SubjectRiskRule,
    SubjectRiskType,
    SubjectVersion,
)
from .risk_engine import (
    CATALOG_FORMAT_VERSION,
    MACHINE_KEY,
    RiskCatalogInvalid,
    catalog_digest,
    evaluate_catalog,
    normalize_patterns,
    validate_catalog_snapshot,
)

PLAIN_TEXT = re.compile(r"^[^<>\x00-\x1f\x7f]*$")


class SubjectRiskError(Exception):
    code = "SUBJECT_RISK_CONFIG_INTEGRITY_ERROR"


class SubjectRiskCatalogVersionConflict(SubjectRiskError):
    code = "SUBJECT_RISK_CATALOG_VERSION_CONFLICT"


class SubjectRiskTypeVersionConflict(SubjectRiskError):
    code = "SUBJECT_RISK_TYPE_VERSION_CONFLICT"


class SubjectRiskRuleVersionConflict(SubjectRiskError):
    code = "SUBJECT_RISK_RULE_VERSION_CONFLICT"


class SubjectReviewStateConflict(SubjectRiskError):
    code = "SUBJECT_REVIEW_STATE_CONFLICT"


class SubjectReviewVersionConflict(SubjectRiskError):
    code = "SUBJECT_REVIEW_VERSION_CONFLICT"


class SubjectReviewReasonRequired(SubjectRiskError):
    code = "SUBJECT_REVIEW_REASON_REQUIRED"


class SubjectReviewPending(SubjectRiskError):
    code = "SUBJECT_REVIEW_PENDING"


class SubjectReviewRejected(SubjectRiskError):
    code = "SUBJECT_REVIEW_REJECTED"


class SubjectFeatureRestricted(SubjectRiskError):
    code = "SUBJECT_FEATURE_RESTRICTED"


def _plain_text(value: str, *, limit: int) -> str:
    value = " ".join(value.split())
    if not value or len(value) > limit or not PLAIN_TEXT.fullmatch(value):
        raise SubjectRiskError
    return value


def _locked_catalog_state() -> SubjectRiskCatalogState:
    state = SubjectRiskCatalogState.objects.select_for_update().get(pk=1)
    return state


def catalog_state() -> SubjectRiskCatalogState:
    state = SubjectRiskCatalogState.objects.get(pk=1)
    return state


def lock_published_catalog_revision() -> SubjectRiskCatalogRevision:
    state = _locked_catalog_state()
    if state.published_revision_id is None:
        raise SubjectRiskError
    revision = SubjectRiskCatalogRevision.objects.select_for_update().get(
        pk=state.published_revision_id
    )
    snapshot = copy.deepcopy(revision.snapshot)
    try:
        validate_catalog_snapshot(snapshot)
    except RiskCatalogInvalid as exc:
        raise SubjectRiskError from exc
    if catalog_digest(snapshot) != revision.snapshot_digest:
        raise SubjectRiskError
    return revision


def published_catalog_revision() -> SubjectRiskCatalogRevision:
    state = catalog_state()
    if state.published_revision_id is None:
        raise SubjectRiskError
    revision = SubjectRiskCatalogRevision.objects.get(pk=state.published_revision_id)
    snapshot = copy.deepcopy(revision.snapshot)
    try:
        validate_catalog_snapshot(snapshot)
    except RiskCatalogInvalid as exc:
        raise SubjectRiskError from exc
    if catalog_digest(snapshot) != revision.snapshot_digest:
        raise SubjectRiskError
    return revision


def build_draft_snapshot() -> dict[str, Any]:
    risk_types = [
        {
            "key": row.key,
            "name": row.name,
            "description": row.description,
            "enabled": row.enabled,
            "manual_review_required": row.manual_review_required,
            "allow_geo_detection": row.allow_geo_detection,
            "allow_article_generation": row.allow_article_generation,
            "allow_image_generation": row.allow_image_generation,
            "require_authoritative_citations": row.require_authoritative_citations,
            "require_disclaimer": row.require_disclaimer,
        }
        for row in SubjectRiskType.objects.order_by("sort_order", "key", "id")
    ]
    rules = [
        {
            "key": row.key,
            "risk_type_key": row.risk_type.key,
            "subject_type_key": row.subject_type.key if row.subject_type is not None else None,
            "field_key": row.field_key,
            "operator": row.operator,
            "patterns": copy.deepcopy(row.patterns),
            "reason_type": row.reason_type,
            "enabled": row.enabled,
        }
        for row in SubjectRiskRule.objects.select_related("risk_type", "subject_type").order_by(
            "priority", "key", "id"
        )
    ]
    return validate_catalog_snapshot(
        {"format_version": CATALOG_FORMAT_VERSION, "risk_types": risk_types, "rules": rules}
    )


@transaction.atomic
def draft_catalog_binding(expected_version: int) -> tuple[int, str]:
    state = _locked_catalog_state()
    if state.version != expected_version:
        raise SubjectRiskCatalogVersionConflict
    return state.version, catalog_digest(build_draft_snapshot())


def _bump_state(state: SubjectRiskCatalogState) -> None:
    state.version += 1
    state.save(update_fields=["version", "updated_at"])


@transaction.atomic
def create_risk_type(*, request, data: dict[str, Any]) -> SubjectRiskType:
    state = _locked_catalog_state()
    if data.pop("expected_catalog_version") != state.version:
        raise SubjectRiskCatalogVersionConflict
    key = data["key"].strip().casefold()
    if not MACHINE_KEY.fullmatch(key):
        raise SubjectRiskError
    data["key"] = key
    data["name"] = _plain_text(data["name"], limit=100)
    data["description"] = _plain_text(data["description"], limit=500) if data["description"] else ""
    try:
        row = SubjectRiskType.objects.create(
            **data, created_by=request.user, updated_by=request.user
        )
    except IntegrityError as exc:
        raise SubjectRiskError from exc
    _bump_state(state)
    record_audit_event(
        request=request,
        category="subject_risk_catalog",
        action_key="subject_risk.type.create",
        outcome="succeeded",
        actor=request.user,
        target_type="subject_risk_type",
        target_id=row.pk,
        safe_after={"key": row.key, "version": row.version},
    )
    return row


@transaction.atomic
def update_risk_type(*, request, risk_type_id, data: dict[str, Any]) -> SubjectRiskType:
    state = _locked_catalog_state()
    if data.pop("expected_catalog_version") != state.version:
        raise SubjectRiskCatalogVersionConflict
    try:
        row = SubjectRiskType.objects.select_for_update().get(pk=risk_type_id)
    except SubjectRiskType.DoesNotExist as exc:
        raise NotFound from exc
    if data.pop("expected_version") != row.version:
        raise SubjectRiskTypeVersionConflict
    before = {"version": row.version, "enabled": row.enabled}
    for key, value in data.items():
        if key in {"name", "description"} and value:
            value = _plain_text(value, limit=100 if key == "name" else 500)
        setattr(row, key, value)
    row.version += 1
    row.updated_by = request.user
    row.save()
    _bump_state(state)
    record_audit_event(
        request=request,
        category="subject_risk_catalog",
        action_key="subject_risk.type.update",
        outcome="succeeded",
        actor=request.user,
        target_type="subject_risk_type",
        target_id=row.pk,
        safe_before=before,
        safe_after={"version": row.version, "enabled": row.enabled},
    )
    return row


@transaction.atomic
def create_risk_rule(*, request, data: dict[str, Any]) -> SubjectRiskRule:
    state = _locked_catalog_state()
    if data.pop("expected_catalog_version") != state.version:
        raise SubjectRiskCatalogVersionConflict
    key = data["key"].strip().casefold()
    if not MACHINE_KEY.fullmatch(key):
        raise SubjectRiskError
    data["key"] = key
    try:
        data["patterns"] = normalize_patterns(data["patterns"])
        row = SubjectRiskRule.objects.create(
            **data, created_by=request.user, updated_by=request.user
        )
    except (IntegrityError, RiskCatalogInvalid) as exc:
        raise SubjectRiskError from exc
    _bump_state(state)
    record_audit_event(
        request=request,
        category="subject_risk_catalog",
        action_key="subject_risk.rule.create",
        outcome="succeeded",
        actor=request.user,
        target_type="subject_risk_rule",
        target_id=row.pk,
        safe_after={"key": row.key, "version": row.version},
    )
    return row


@transaction.atomic
def update_risk_rule(*, request, risk_rule_id, data: dict[str, Any]) -> SubjectRiskRule:
    state = _locked_catalog_state()
    if data.pop("expected_catalog_version") != state.version:
        raise SubjectRiskCatalogVersionConflict
    try:
        row = SubjectRiskRule.objects.select_for_update().get(pk=risk_rule_id)
    except SubjectRiskRule.DoesNotExist as exc:
        raise NotFound from exc
    if data.pop("expected_version") != row.version:
        raise SubjectRiskRuleVersionConflict
    before = {"version": row.version, "enabled": row.enabled}
    if "patterns" in data:
        try:
            data["patterns"] = normalize_patterns(data["patterns"])
        except RiskCatalogInvalid as exc:
            raise SubjectRiskError from exc
    for key, value in data.items():
        setattr(row, key, value)
    row.version += 1
    row.updated_by = request.user
    row.save()
    _bump_state(state)
    record_audit_event(
        request=request,
        category="subject_risk_catalog",
        action_key="subject_risk.rule.update",
        outcome="succeeded",
        actor=request.user,
        target_type="subject_risk_rule",
        target_id=row.pk,
        safe_before=before,
        safe_after={"version": row.version, "enabled": row.enabled},
    )
    return row


@transaction.atomic
def publish_catalog(
    *,
    request,
    expected_version: int,
    expected_digest: str,
    approval_request: ApprovalRequest,
) -> SubjectRiskCatalogRevision:
    state = _locked_catalog_state()
    if state.version != expected_version:
        raise SubjectRiskCatalogVersionConflict
    snapshot = build_draft_snapshot()
    digest = catalog_digest(snapshot)
    if digest != expected_digest:
        raise SubjectRiskCatalogVersionConflict
    previous = state.published_revision
    if previous is not None and previous.snapshot_digest == digest:
        raise SubjectRiskError
    revision_no = (
        SubjectRiskCatalogRevision.objects.select_for_update()
        .order_by("-revision_no")
        .values_list("revision_no", flat=True)
        .first()
        or 0
    ) + 1
    revision = SubjectRiskCatalogRevision.objects.create(
        revision_no=revision_no,
        draft_version=expected_version,
        snapshot=copy.deepcopy(snapshot),
        snapshot_digest=digest,
        published_by=request.user,
        approval_request=approval_request,
    )
    state.published_revision = revision
    state.save(update_fields=["published_revision", "updated_at"])
    _bump_state(state)
    return revision


def supersede_pending_review(*, subject: Subject, actor: User, request_id) -> None:
    pending = (
        SubjectReview.objects.select_for_update()
        .filter(subject=subject, status=SubjectReview.Status.PENDING)
        .first()
    )
    if pending is None:
        return
    pending.status = SubjectReview.Status.SUPERSEDED
    pending.version += 1
    pending.save(update_fields=["status", "version", "updated_at"])
    SubjectReviewEvent.objects.create(
        review=pending,
        event_type=SubjectReviewEvent.EventType.SUPERSEDED,
        from_status=SubjectReview.Status.PENDING,
        to_status=SubjectReview.Status.SUPERSEDED,
        safe_summary={"subject_version_id": str(pending.subject_version_id)},
        actor=actor,
        request_id=request_id,
    )


def assess_subject_version(
    *,
    subject: Subject,
    version: SubjectVersion,
    revision: SubjectRiskCatalogRevision,
    actor: User | None,
    request_id,
    create_review: bool = True,
) -> SubjectRiskAssessment:
    hits = evaluate_catalog(
        snapshot=copy.deepcopy(revision.snapshot),
        subject_type_key=subject.subject_type.key,
        schema_snapshot=version.schema_snapshot,
        field_values=version.field_values,
    )
    type_by_key = {item["key"]: item for item in revision.snapshot["risk_types"]}
    review_required = any(
        type_by_key[hit["risk_type_key"]]["manual_review_required"] for hit in hits
    )
    outcome = (
        SubjectRiskAssessment.Outcome.REVIEW_REQUIRED
        if review_required
        else SubjectRiskAssessment.Outcome.RESTRICTED
        if hits
        else SubjectRiskAssessment.Outcome.CLEAR
    )
    assessment = SubjectRiskAssessment.objects.create(
        subject_version=version,
        catalog_revision=revision,
        semantic_digest=version.semantic_digest,
        outcome=outcome,
    )
    SubjectRiskHit.objects.bulk_create(
        [SubjectRiskHit(assessment=assessment, **hit) for hit in hits]
    )
    if review_required and create_review:
        review = SubjectReview.objects.create(
            assessment=assessment, subject=subject, subject_version=version
        )
        SubjectReviewEvent.objects.create(
            review=review,
            event_type=SubjectReviewEvent.EventType.REQUESTED,
            from_status="",
            to_status=SubjectReview.Status.PENDING,
            safe_summary={"subject_version_id": str(version.pk)},
            actor=actor,
            request_id=request_id,
        )
    return assessment


def assess_existing_subject_versions(*, request_id=None) -> dict[str, Any]:
    revision = published_catalog_revision()
    fixed_revision_id = revision.pk
    version_ids = list(
        SubjectVersion.objects.filter(risk_assessment__isnull=True)
        .order_by("subject_id", "version_no", "id")
        .values_list("id", flat=True)
    )
    assessed = 0
    reviews_created = 0
    for version_id in version_ids:
        with transaction.atomic():
            pending_version = SubjectVersion.objects.only("subject_id").get(pk=version_id)
            user_id = Subject.objects.values_list("user_id", flat=True).get(
                pk=pending_version.subject_id
            )
            User.objects.select_for_update().get(pk=user_id)
            subject = (
                Subject.objects.select_for_update()
                .select_related("subject_type")
                .get(pk=pending_version.subject_id)
            )
            version = SubjectVersion.objects.select_for_update().get(pk=version_id)
            if SubjectRiskAssessment.objects.filter(subject_version=version).exists():
                continue
            fixed_revision = SubjectRiskCatalogRevision.objects.get(pk=fixed_revision_id)
            create_review = subject.current_version_id == version.pk
            assessment = assess_subject_version(
                subject=subject,
                version=version,
                revision=fixed_revision,
                actor=None,
                request_id=request_id or uuid.uuid4(),
                create_review=create_review,
            )
            assessed += 1
            reviews_created += int(
                create_review
                and assessment.outcome == SubjectRiskAssessment.Outcome.REVIEW_REQUIRED
            )
    return {
        "revision_id": str(fixed_revision_id),
        "assessed": assessed,
        "reviews_created": reviews_created,
    }


def scoped_reviews(*, user: User, admin_context) -> QuerySet[SubjectReview]:
    customer_ids = scoped_customers(user, admin_context).values("id")
    return SubjectReview.objects.filter(subject__user_id__in=customer_ids)


def scoped_review_or_404(*, user: User, admin_context, review_id, lock=False) -> SubjectReview:
    rows = scoped_reviews(user=user, admin_context=admin_context).select_related(
        "subject",
        "subject__user",
        "subject_version",
        "assessment",
        "assessment__catalog_revision",
    )
    if lock:
        rows = rows.select_for_update()
    try:
        return rows.get(pk=review_id)
    except SubjectReview.DoesNotExist as exc:
        raise NotFound from exc


@transaction.atomic
def decide_review(
    *,
    request,
    review_id,
    decision: str,
    expected_version: int,
    public_reason: str,
    internal_note: str,
) -> SubjectReview:
    scoped = scoped_review_or_404(
        user=request.user,
        admin_context=request.admin_context,
        review_id=review_id,
        lock=False,
    )
    user = User.objects.select_for_update().get(pk=scoped.subject.user_id)
    subject = Subject.objects.select_for_update().get(pk=scoped.subject_id)
    review = SubjectReview.objects.select_for_update().get(pk=scoped.pk)
    if (
        not scoped_reviews(user=request.user, admin_context=request.admin_context)
        .filter(pk=review.pk)
        .exists()
    ):
        raise NotFound
    if review.version != expected_version:
        raise SubjectReviewVersionConflict
    if (
        review.status != SubjectReview.Status.PENDING
        or subject.current_version_id != review.subject_version_id
    ):
        raise SubjectReviewStateConflict
    if decision not in {
        SubjectReview.Status.APPROVED,
        SubjectReview.Status.REJECTED,
    }:
        raise SubjectReviewStateConflict
    public_reason = _plain_text(public_reason, limit=500) if public_reason else ""
    internal_note = _plain_text(internal_note, limit=1000) if internal_note else ""
    if decision == SubjectReview.Status.REJECTED and not public_reason:
        raise SubjectReviewReasonRequired
    before = {"status": review.status, "version": review.version}
    review.status = decision
    review.public_reason = public_reason
    review.internal_note = internal_note
    review.reviewed_by = request.user
    review.reviewed_at = timezone.now()
    review.version += 1
    review.save()
    SubjectReviewEvent.objects.create(
        review=review,
        event_type=(
            SubjectReviewEvent.EventType.APPROVED
            if decision == SubjectReview.Status.APPROVED
            else SubjectReviewEvent.EventType.REJECTED
        ),
        from_status=SubjectReview.Status.PENDING,
        to_status=decision,
        safe_summary={"subject_version_id": str(review.subject_version_id)},
        actor=request.user,
        request_id=request.request_id,
    )
    Notification.objects.create(
        recipient=user,
        notification_type=(
            Notification.NotificationType.SUBJECT_REVIEW_APPROVED
            if decision == SubjectReview.Status.APPROVED
            else Notification.NotificationType.SUBJECT_REVIEW_REJECTED
        ),
        title="\u4e3b\u4f53\u8d44\u6599\u5ba1\u6838\u7ed3\u679c",
        safe_summary="\u4e3b\u4f53\u8d44\u6599\u5ba1\u6838\u5df2\u5b8c\u6210\uff0c\u8bf7\u67e5\u770b\u4e3b\u4f53\u8be6\u60c5\u3002",
    )
    record_audit_event(
        request=request,
        category="subject_review",
        action_key=f"subject_risk.review.{decision}",
        outcome="succeeded",
        actor=request.user,
        subject=user,
        target_type="subject_review",
        target_id=review.pk,
        safe_before=before,
        safe_after={"status": decision, "version": review.version},
    )
    return review


@dataclass(frozen=True)
class SubjectCapabilities:
    geo_detection: bool
    article_generation: bool
    image_generation: bool
    require_authoritative_citations: bool
    require_disclaimer: bool


def capabilities_for_subject(subject: Subject) -> SubjectCapabilities:
    if subject.current_version_id is None:
        raise SubjectReviewPending
    current_version = subject.current_version
    if current_version is None:
        raise SubjectReviewPending
    try:
        assessment = current_version.risk_assessment
    except SubjectRiskAssessment.DoesNotExist as exc:
        raise SubjectRiskError from exc
    review = getattr(assessment, "review", None)
    if review is not None and review.status == SubjectReview.Status.PENDING:
        raise SubjectReviewPending
    if review is not None and review.status in {
        SubjectReview.Status.REJECTED,
        SubjectReview.Status.SUPERSEDED,
    }:
        raise SubjectReviewRejected
    revision = published_catalog_revision()
    policies = {item["key"]: item for item in revision.snapshot["risk_types"]}
    hit_keys = [hit.risk_type_key for hit in SubjectRiskHit.objects.filter(assessment=assessment)]
    return merge_feature_policies(policies=policies, hit_keys=hit_keys)


def merge_feature_policies(
    *, policies: dict[str, dict[str, Any]], hit_keys: list[str]
) -> SubjectCapabilities:
    missing_policy_keys = set(hit_keys) - set(policies)
    if missing_policy_keys:
        raise SubjectRiskError
    matched = [policies[key] for key in hit_keys]
    return SubjectCapabilities(
        geo_detection=all(item["allow_geo_detection"] for item in matched),
        article_generation=all(item["allow_article_generation"] for item in matched),
        image_generation=all(item["allow_image_generation"] for item in matched),
        require_authoritative_citations=any(
            item["require_authoritative_citations"] for item in matched
        ),
        require_disclaimer=any(item["require_disclaimer"] for item in matched),
    )


def subject_risk_summary(subject: Subject) -> dict[str, Any]:
    if subject.current_version_id is None:
        return {"status": "not_assessed", "review_id": None, "public_reason": ""}
    current_version = subject.current_version
    if current_version is None:
        return {"status": "not_assessed", "review_id": None, "public_reason": ""}
    try:
        assessment = current_version.risk_assessment
    except SubjectRiskAssessment.DoesNotExist:
        return {"status": "unavailable", "review_id": None, "public_reason": ""}
    try:
        review = assessment.review
    except SubjectReview.DoesNotExist:
        review = None
    return {
        "status": review.status if review is not None else assessment.outcome,
        "review_id": str(review.pk) if review is not None else None,
        "public_reason": review.public_reason if review is not None else "",
    }


def ensure_subject_feature_allowed(subject: Subject, feature: str) -> None:
    capabilities = capabilities_for_subject(subject)
    if not getattr(capabilities, feature, False):
        raise SubjectFeatureRestricted
