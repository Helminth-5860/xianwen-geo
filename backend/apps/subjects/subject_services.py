from dataclasses import dataclass
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.plans.models import Subscription, SubscriptionChange
from apps.plans.subscription_services import effective_entitlement_snapshot
from apps.users.models import Tenant, User

from .models import Subject, SubjectBusinessProfile, SubjectContext, SubjectEvent, SubjectType
from .schema_snapshots import (
    SCHEMA_SNAPSHOT_FORMAT_VERSION,
    SnapshotValueError,
    assert_snapshot_integrity,
    build_schema_snapshot,
    merge_and_validate_values,
)

WORKSPACE_SUBJECT_LIMIT = 1


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


class SubjectIdentityLocked(SubjectBusinessError):
    code = "SUBJECT_IDENTITY_LOCKED"


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


def workspace_subject_filter(user: User, *, prefix: str = "") -> Q:
    """Return the subject ownership predicate for the user's workspace."""

    if user.tenant_id is not None:
        return Q(**{f"{prefix}tenant_id": user.tenant_id})
    return Q(
        **{
            f"{prefix}tenant__isnull": True,
            f"{prefix}user_id": user.pk,
        }
    )


def _workspace_subject_filter(user: User) -> Q:
    return workspace_subject_filter(user)


def _workspace_users(user: User):
    if user.tenant_id is not None:
        return User.objects.filter(tenant_id=user.tenant_id)
    return User.objects.filter(pk=user.pk)


def _lock_workspace(user: User) -> None:
    if user.tenant_id is not None:
        Tenant.objects.select_for_update().get(pk=user.tenant_id)


def active_subject_for_user(user: User) -> Subject | None:
    return (
        Subject.objects.filter(_workspace_subject_filter(user), status=Subject.Status.ACTIVE)
        .select_related("subject_type", "current_version", "business_profile")
        .first()
    )


def _limit_from_snapshot(snapshot: Any) -> int:
    # A workspace always owns exactly one active subject. This is a product
    # invariant rather than a commercial entitlement, so plan snapshots no
    # longer carry or control a subject count.
    if not isinstance(snapshot, dict):
        raise SubjectEntitlementIntegrityError
    return WORKSPACE_SUBJECT_LIMIT


def subject_limit_preview(*, user: User, target_snapshot: Any) -> SubjectLimitPreview:
    target_limit = _limit_from_snapshot(target_snapshot)
    active_count = Subject.objects.filter(
        _workspace_subject_filter(user), status=Subject.Status.ACTIVE
    ).count()
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
        )
        .select_related("target_plan_version")
        .order_by("effective_at", "id")
    )
    for change in changes:
        limits.append(_limit_from_snapshot(change.target_plan_version.effective_config))
    return min(limits) if limits else None


def effective_subject_activation_limit(*, user: User, subscription: Subscription) -> int:
    current_limit = _limit_from_snapshot(effective_entitlement_snapshot(subscription))
    if user.is_test_account:
        return current_limit
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
        Subject.objects.filter(_workspace_subject_filter(user))
        .select_related("subject_type", "current_version", "business_profile")
        .order_by("-updated_at", "id")
    )


def subject_for_user_or_404(*, user: User, subject_id, lock: bool = False) -> Subject:
    query = Subject.objects.filter(_workspace_subject_filter(user)).select_related(
        "subject_type", "current_version", "business_profile"
    )
    if lock:
        query = query.select_for_update(of=("self",))
    try:
        return query.get(pk=subject_id)
    except Subject.DoesNotExist as exc:
        raise NotFound from exc


def subject_context_for_user(user: User) -> SubjectContext | None:
    active_subject = active_subject_for_user(user)
    context = SubjectContext.objects.filter(user=user).select_related("current_subject").first()
    active_id = active_subject.pk if active_subject is not None else None
    if context is None:
        return SubjectContext.objects.create(user=user, current_subject=active_subject)
    if context.current_subject_id != active_id:
        context.current_subject = active_subject
        context.version += 1
        context.save(update_fields=["current_subject", "version", "updated_at"])
    return context


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
    _lock_workspace(user)
    if Subject.objects.filter(
        _workspace_subject_filter(user), status=Subject.Status.ACTIVE
    ).exists():
        raise SubjectLimitReached
    moment = timezone.now()
    subscription = _effective_subscription_locked(user=user, moment=moment)
    if not user.is_test_account:
        existing_count = (
            Subject.objects.filter(user=user).exclude(status=Subject.Status.ARCHIVED).count()
        )
        if subscription is None:
            if existing_count >= 1:
                raise SubjectLimitReached
        else:
            limit = effective_subject_activation_limit(user=user, subscription=subscription)
            if existing_count >= limit:
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
        tenant_id=user.tenant_id,
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
        summary="Subject created.",
    )
    SubjectContext.objects.get_or_create(user=user, defaults={"current_subject": None})
    return subject


@transaction.atomic
def mark_subject_usable_after_save(*, user_id, subject_id, request_id) -> Subject:
    """Make a successfully saved subject usable and select the first saved subject globally."""
    user = User.objects.select_for_update().get(pk=user_id)
    _ensure_subject_write_allowed(user)
    _lock_workspace(user)
    subject = subject_for_user_or_404(user=user, subject_id=subject_id, lock=True)
    if subject.status == Subject.Status.ARCHIVED or subject.current_version_id is None:
        raise SubjectStateConflict
    if subject.status != Subject.Status.ACTIVE:
        if (
            Subject.objects.filter(_workspace_subject_filter(user), status=Subject.Status.ACTIVE)
            .exclude(pk=subject.pk)
            .exists()
        ):
            raise SubjectLimitReached
        previous = subject.status
        subject.status = Subject.Status.ACTIVE
        subject.identity_bound_at = timezone.now()
        subject.bound_official_name = subject.current_version.official_name.strip()
        try:
            profile = subject.business_profile
        except SubjectBusinessProfile.DoesNotExist:
            profile = None
        subject.bound_unified_social_credit_code = (
            profile.unified_social_credit_code.strip().upper() if profile is not None else ""
        )
        subject.version += 1
        try:
            subject.save(
                update_fields=[
                    "status",
                    "identity_bound_at",
                    "bound_official_name",
                    "bound_unified_social_credit_code",
                    "version",
                    "updated_at",
                ]
            )
        except IntegrityError as exc:
            raise SubjectLimitReached from exc
        _subject_event(
            subject=subject,
            event_type=SubjectEvent.EventType.ACTIVATED,
            from_status=previous,
            actor=user,
            request_id=request_id,
            summary="Saved subject became usable.",
        )
    selected = False
    for workspace_user in _workspace_users(user).select_for_update():
        context = SubjectContext.objects.select_for_update().filter(user=workspace_user).first()
        if context is None:
            SubjectContext.objects.create(user=workspace_user, current_subject=subject)
            selected = True
        elif context.current_subject_id != subject.pk:
            context.current_subject = subject
            context.version += 1
            context.save(update_fields=["current_subject", "version", "updated_at"])
            selected = True
    if selected:
        _subject_event(
            subject=subject,
            event_type=SubjectEvent.EventType.CURRENT_SELECTED,
            from_status=subject.status,
            actor=user,
            request_id=request_id,
            summary="First saved subject selected as current.",
        )
    return subject


def merge_subject_draft_values_locked(
    *,
    user: User,
    subject: Subject,
    values: dict[str, Any],
) -> Subject:
    """Apply a validated draft patch to an already locked owner/subject pair."""
    _ensure_subject_write_allowed(user)
    if (
        not Subject.objects.filter(_workspace_subject_filter(user), pk=subject.pk).exists()
        or subject.status == Subject.Status.ARCHIVED
    ):
        raise SubjectStateConflict
    if subject.identity_bound_at is not None and "name" in values:
        candidate_name = values.get("name")
        normalized_name = candidate_name.strip() if isinstance(candidate_name, str) else ""
        if normalized_name != subject.bound_official_name:
            raise SubjectIdentityLocked
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
def update_subject_draft(
    *,
    user_id,
    subject_id,
    expected_version: int,
    values: dict[str, Any],
    profile_values: dict[str, Any] | None = None,
) -> Subject:
    user = User.objects.select_for_update().get(pk=user_id)
    subject = subject_for_user_or_404(user=user, subject_id=subject_id, lock=True)
    if subject.version != expected_version:
        raise SubjectVersionConflict
    subject = merge_subject_draft_values_locked(user=user, subject=subject, values=values)
    if profile_values is not None:
        profile_values = dict(profile_values)
        if subject.identity_bound_at is not None:
            candidate_credit = (
                str(
                    profile_values.get(
                        "unified_social_credit_code",
                        subject.bound_unified_social_credit_code,
                    )
                    or ""
                )
                .strip()
                .upper()
            )
            if candidate_credit != subject.bound_unified_social_credit_code:
                raise SubjectIdentityLocked
        profile_values["legal_entity_type"] = (
            SubjectBusinessProfile.LegalEntityType.INDIVIDUAL_BUSINESS
            if subject.subject_type.key == "individual_business"
            else SubjectBusinessProfile.LegalEntityType.COMPANY
        )
        if subject.subject_type.key not in {"enterprise", "individual_business"}:
            profile_values["unified_social_credit_code"] = ""
        profile, _ = SubjectBusinessProfile.objects.update_or_create(
            subject=subject,
            defaults=profile_values,
        )
        subject.business_profile = profile
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
    _lock_workspace(user)
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
        replacement = (
            Subject.objects.select_for_update()
            .filter(
                user=user,
                status=Subject.Status.ACTIVE,
                current_version__isnull=False,
            )
            .exclude(pk=subject.pk)
            .order_by("-updated_at", "id")
            .first()
        )
        context.current_subject = replacement
        context.version += 1
        context.save(update_fields=["current_subject", "version", "updated_at"])
        _subject_event(
            subject=subject,
            event_type=SubjectEvent.EventType.CURRENT_CLEARED,
            from_status=previous,
            actor=user,
            request_id=request_id,
            summary="Deleted current subject context cleared.",
        )
        if replacement is not None:
            _subject_event(
                subject=replacement,
                event_type=SubjectEvent.EventType.CURRENT_SELECTED,
                from_status=replacement.status,
                actor=user,
                request_id=request_id,
                summary="Replacement current subject selected.",
            )
    _subject_event(
        subject=subject,
        event_type=SubjectEvent.EventType.ARCHIVED,
        from_status=previous,
        actor=user,
        request_id=request_id,
        summary="Subject soft deleted.",
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
    active_count = Subject.objects.filter(
        _workspace_subject_filter(user), status=Subject.Status.ACTIVE
    ).count()
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
    _lock_workspace(user)
    subject = subject_for_user_or_404(user=user, subject_id=subject_id, lock=True)
    active_subject = (
        Subject.objects.select_for_update()
        .filter(_workspace_subject_filter(user), status=Subject.Status.ACTIVE)
        .first()
    )
    if (
        active_subject is None
        or active_subject.pk != subject.pk
        or subject.current_version_id is None
    ):
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
