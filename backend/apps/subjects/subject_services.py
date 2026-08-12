from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.admin_rbac.models import ApprovalRequest
from apps.plans.models import Subscription, SubscriptionChange
from apps.users.models import User

from .models import Subject, SubjectContext, SubjectEvent, SubjectType
from .schema_snapshots import (
    SCHEMA_SNAPSHOT_FORMAT_VERSION,
    SnapshotValueError,
    assert_snapshot_integrity,
    build_schema_snapshot,
    merge_and_validate_values,
)

SUBJECT_ACTIVE_LIMIT_KEY = "subject_active_limit"
SUBJECT_ACTIVE_LIMIT_MAXIMUM = 1_000_000


class SubjectBusinessError(Exception):
    code = "SUBJECT_STATE_CONFLICT"


class SubjectSchemaMismatch(SubjectBusinessError):
    code = "SUBJECT_SCHEMA_MISMATCH"


class SubjectValuesInvalid(SubjectBusinessError):
    code = "SUBJECT_FIELD_VALUES_INVALID"

    def __init__(self, field_key: str = ""):
        self.field_key = field_key
        super().__init__(field_key)


class SubjectLimitReached(SubjectBusinessError):
    code = "SUBJECT_LIMIT_REACHED"


class SubjectLimitReconciliationRequired(SubjectBusinessError):
    code = "SUBJECT_LIMIT_RECONCILIATION_REQUIRED"


class SubjectEntitlementIntegrityError(SubjectBusinessError):
    code = "SUBJECT_ENTITLEMENT_INTEGRITY_ERROR"


class SubjectVersionConflict(SubjectBusinessError):
    code = "SUBJECT_VERSION_CONFLICT"


class SubjectContextVersionConflict(SubjectBusinessError):
    code = "SUBJECT_CURRENT_VERSION_CONFLICT"


class SubjectStateConflict(SubjectBusinessError):
    code = "SUBJECT_STATE_CONFLICT"


class SubjectPlanRequired(SubjectBusinessError):
    code = "PLAN_REQUIRED"


class SubjectAccountReadOnly(SubjectBusinessError):
    code = "ACCOUNT_UNAVAILABLE"


@dataclass(frozen=True)
class SubjectLimitPreview:
    active_count: int
    target_limit: int
    required_archive_count: int


def _ensure_subject_write_allowed(user: User) -> None:
    if not user.is_active or user.account_status != User.AccountStatus.ACTIVE:
        raise SubjectAccountReadOnly


def _limit_from_snapshot(snapshot: Any) -> int:
    if not isinstance(snapshot, dict):
        raise SubjectEntitlementIntegrityError
    limits = snapshot.get("limits")
    if not isinstance(limits, dict):
        raise SubjectEntitlementIntegrityError
    value = limits.get(SUBJECT_ACTIVE_LIMIT_KEY)
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > SUBJECT_ACTIVE_LIMIT_MAXIMUM
    ):
        raise SubjectEntitlementIntegrityError
    return value


def subject_limit_preview(*, user: User, target_snapshot: Any) -> SubjectLimitPreview:
    target_limit = _limit_from_snapshot(target_snapshot)
    active_count = Subject.objects.filter(user=user, status=Subject.Status.ACTIVE).count()
    return SubjectLimitPreview(
        active_count=active_count,
        target_limit=target_limit,
        required_archive_count=max(active_count - target_limit, 0),
    )


def assert_target_subject_limit_locked(*, user: User, target_snapshot: Any) -> None:
    preview = subject_limit_preview(user=user, target_snapshot=target_snapshot)
    if preview.required_archive_count:
        raise SubjectLimitReconciliationRequired


def _effective_subscription_locked(*, user: User, moment):
    return (
        Subscription.objects.select_for_update()
        .filter(
            user=user,
            status=Subscription.Status.ACTIVE,
            starts_at__lte=moment,
            ends_at__gt=moment,
        )
        .order_by("starts_at", "id")
        .first()
    )


def _future_scheduled_limit(*, user: User, current: Subscription) -> int | None:
    limits: list[int] = []
    changes = (
        SubscriptionChange.objects.filter(
            user=user,
            from_subscription=current,
            status=SubscriptionChange.Status.SCHEDULED,
            change_type=SubscriptionChange.ChangeType.RENEWAL,
            source_approval__action_key="subscription.change",
            source_approval__status=ApprovalRequest.Status.EXECUTED,
        )
        .select_related("target_plan_version")
        .order_by("effective_at", "id")
    )
    for change in changes:
        limits.append(_limit_from_snapshot(change.target_plan_version.effective_config))
    return min(limits) if limits else None


def effective_subject_activation_limit(*, user: User, subscription: Subscription) -> int:
    current_limit = _limit_from_snapshot(subscription.entitlement_snapshot)
    future_limit = _future_scheduled_limit(user=user, current=subscription)
    return min(current_limit, future_limit) if future_limit is not None else current_limit


def _subject_event(
    *,
    subject: Subject,
    event_type: str,
    from_status: str,
    actor: User,
    request_id,
    summary: str,
) -> SubjectEvent:
    return SubjectEvent.objects.create(
        subject=subject,
        event_type=event_type,
        from_status=from_status,
        to_status=subject.status,
        safe_summary={"message": summary},
        actor=actor,
        request_id=request_id,
    )


def subjects_for_user(user: User):
    return (
        Subject.objects.filter(user=user)
        .select_related("subject_type", "current_version")
        .order_by("-updated_at", "id")
    )


def subject_for_user_or_404(*, user: User, subject_id, lock: bool = False) -> Subject:
    query = Subject.objects.filter(user=user).select_related("subject_type", "current_version")
    if lock:
        query = query.select_for_update(of=("self",))
    try:
        return query.get(pk=subject_id)
    except Subject.DoesNotExist as exc:
        raise NotFound from exc


def subject_context_for_user(user: User) -> SubjectContext | None:
    return SubjectContext.objects.filter(user=user).select_related("current_subject").first()


@transaction.atomic
def create_subject(
    *,
    user_id,
    subject_type_id,
    expected_schema_version: int,
    initial_values: dict[str, Any],
    request_id,
) -> Subject:
    user = User.objects.select_for_update().get(pk=user_id)
    _ensure_subject_write_allowed(user)
    moment = timezone.now()
    subscription = _effective_subscription_locked(user=user, moment=moment)
    if (
        subscription is None
        and Subject.objects.filter(user=user, status=Subject.Status.DRAFT).exists()
    ):
        raise SubjectLimitReached
    try:
        subject_type = SubjectType.objects.select_for_update().get(
            pk=subject_type_id,
            status=SubjectType.Status.ACTIVE,
        )
    except SubjectType.DoesNotExist as exc:
        raise NotFound from exc
    if subject_type.schema_version != expected_schema_version:
        raise SubjectSchemaMismatch
    snapshot, digest = build_schema_snapshot(subject_type)
    try:
        values = merge_and_validate_values(snapshot, updates=initial_values)
    except SnapshotValueError as exc:
        raise SubjectValuesInvalid(exc.field_key) from exc
    subject = Subject.objects.create(
        user=user,
        subject_type=subject_type,
        status=Subject.Status.DRAFT,
        draft_values=values,
        schema_version=subject_type.schema_version,
        schema_snapshot_format_version=SCHEMA_SNAPSHOT_FORMAT_VERSION,
        schema_snapshot=snapshot,
        schema_digest=digest,
    )
    from apps.documents.exceptions import FileContentInvalid
    from apps.documents.services import validate_document_references

    try:
        validate_document_references(
            user_id=user.pk,
            subject_id=subject.pk,
            schema_snapshot=snapshot,
            field_values=values,
        )
    except FileContentInvalid as exc:
        raise SubjectValuesInvalid("document_version_id") from exc
    _subject_event(
        subject=subject,
        event_type=SubjectEvent.EventType.CREATED,
        from_status="",
        actor=user,
        request_id=request_id,
        summary="Subject draft created.",
    )
    context = SubjectContext.objects.select_for_update().filter(user=user).first()
    if context is None:
        SubjectContext.objects.create(user=user, current_subject=subject)
        _subject_event(
            subject=subject,
            event_type=SubjectEvent.EventType.CURRENT_SELECTED,
            from_status=subject.status,
            actor=user,
            request_id=request_id,
            summary="First subject selected as current.",
        )
    return subject


@transaction.atomic
def update_subject_draft(
    *,
    user_id,
    subject_id,
    expected_version: int,
    values: dict[str, Any],
) -> Subject:
    user = User.objects.select_for_update().get(pk=user_id)
    _ensure_subject_write_allowed(user)
    subject = subject_for_user_or_404(user=user, subject_id=subject_id, lock=True)
    if subject.version != expected_version:
        raise SubjectVersionConflict
    if subject.status == Subject.Status.ARCHIVED:
        raise SubjectStateConflict
    try:
        assert_snapshot_integrity(subject.schema_snapshot, subject.schema_digest)
        merged = merge_and_validate_values(
            subject.schema_snapshot,
            current=subject.draft_values,
            updates=values,
        )
        from apps.documents.exceptions import FileContentInvalid
        from apps.documents.services import validate_document_references

        validate_document_references(
            user_id=user.pk,
            subject_id=subject.pk,
            schema_snapshot=subject.schema_snapshot,
            field_values=merged,
        )
    except SnapshotValueError as exc:
        raise SubjectValuesInvalid(exc.field_key) from exc
    except FileContentInvalid as exc:
        raise SubjectValuesInvalid("document_version_id") from exc
    except ValueError as exc:
        raise SubjectEntitlementIntegrityError from exc
    subject.draft_values = merged
    subject.version += 1
    subject.save(update_fields=["draft_values", "version", "updated_at"])
    return subject


@transaction.atomic
def archive_subject(
    *,
    user_id,
    subject_id,
    expected_version: int,
    request_id,
) -> Subject:
    user = User.objects.select_for_update().get(pk=user_id)
    _ensure_subject_write_allowed(user)
    subject = subject_for_user_or_404(user=user, subject_id=subject_id, lock=True)
    if subject.version != expected_version:
        raise SubjectVersionConflict
    if subject.status not in {Subject.Status.DRAFT, Subject.Status.ACTIVE}:
        raise SubjectStateConflict
    previous = subject.status
    subject.status = Subject.Status.ARCHIVED
    subject.version += 1
    subject.save(update_fields=["status", "version", "updated_at"])
    context = SubjectContext.objects.select_for_update().filter(user=user).first()
    if context is not None and context.current_subject_id == subject.pk:
        context.current_subject = None
        context.version += 1
        context.save(update_fields=["current_subject", "version", "updated_at"])
        _subject_event(
            subject=subject,
            event_type=SubjectEvent.EventType.CURRENT_CLEARED,
            from_status=subject.status,
            actor=user,
            request_id=request_id,
            summary="Archived current subject cleared.",
        )
    _subject_event(
        subject=subject,
        event_type=SubjectEvent.EventType.ARCHIVED,
        from_status=previous,
        actor=user,
        request_id=request_id,
        summary="Subject archived.",
    )
    return subject


@transaction.atomic
def activate_subject(
    *,
    user_id,
    subject_id,
    expected_version: int,
    request_id,
) -> Subject:
    user = User.objects.select_for_update().get(pk=user_id)
    _ensure_subject_write_allowed(user)
    moment = timezone.now()
    subscription = _effective_subscription_locked(user=user, moment=moment)
    if subscription is None:
        raise SubjectPlanRequired
    subject = subject_for_user_or_404(user=user, subject_id=subject_id, lock=True)
    if subject.version != expected_version:
        raise SubjectVersionConflict
    if subject.status not in {Subject.Status.DRAFT, Subject.Status.ARCHIVED}:
        raise SubjectStateConflict
    if not SubjectType.objects.filter(
        pk=subject.subject_type_id, status=SubjectType.Status.ACTIVE
    ).exists():
        raise SubjectStateConflict
    limit = effective_subject_activation_limit(user=user, subscription=subscription)
    active_count = Subject.objects.filter(user=user, status=Subject.Status.ACTIVE).count()
    if active_count >= limit:
        raise SubjectLimitReached
    previous = subject.status
    subject.status = Subject.Status.ACTIVE
    subject.version += 1
    subject.save(update_fields=["status", "version", "updated_at"])
    _subject_event(
        subject=subject,
        event_type=SubjectEvent.EventType.ACTIVATED,
        from_status=previous,
        actor=user,
        request_id=request_id,
        summary="Subject activated.",
    )
    return subject


@transaction.atomic
def set_current_subject(
    *,
    user_id,
    subject_id,
    expected_version: int,
    request_id,
) -> SubjectContext:
    user = User.objects.select_for_update().get(pk=user_id)
    _ensure_subject_write_allowed(user)
    subject = subject_for_user_or_404(user=user, subject_id=subject_id, lock=True)
    if subject.status == Subject.Status.ARCHIVED:
        raise SubjectStateConflict
    context = SubjectContext.objects.select_for_update().filter(user=user).first()
    if context is None:
        raise SubjectContextVersionConflict
    if context.version != expected_version:
        raise SubjectContextVersionConflict
    if context.current_subject_id == subject.pk:
        return context
    context.current_subject = subject
    context.version += 1
    context.save(update_fields=["current_subject", "version", "updated_at"])
    _subject_event(
        subject=subject,
        event_type=SubjectEvent.EventType.CURRENT_SELECTED,
        from_status=subject.status,
        actor=user,
        request_id=request_id,
        summary="Current subject selected.",
    )
    return context
