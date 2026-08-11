from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.admin_rbac.permissions import AdminContext
from apps.admin_rbac.scopes import scoped_customers
from apps.quotas.exceptions import QuotaHoldStateConflict
from apps.quotas.services import (
    apply_subscription_change_quotas,
    subscription_has_unsettled_holds,
)
from apps.users.models import Notification, User

from .change_idempotency import PlanChangeDigests
from .models import (
    Plan,
    PlanVersion,
    Subscription,
    SubscriptionChange,
    SubscriptionChangeEvent,
)
from .subscription_services import (
    SubscriptionError,
    SubscriptionPlanUnavailable,
    SubscriptionPlanVersionMismatch,
    SubscriptionSubjectLimitReconciliationRequired,
    SubscriptionVersionConflict,
    _create_active_subscription,
    _ends_at,
    _lock_plan_and_version,
    _subscription_event,
    _validate_snapshot,
    normalize_note,
)


class SubscriptionChangeError(SubscriptionError):
    pass


class SubscriptionChangeClassificationInvalid(SubscriptionChangeError):
    code = "SUBSCRIPTION_CHANGE_CLASSIFICATION_INVALID"


class SubscriptionChangePolicyInvalid(SubscriptionChangeError):
    code = "SUBSCRIPTION_CHANGE_POLICY_INVALID"


class SubscriptionChangeActiveHolds(SubscriptionChangeError):
    code = "SUBSCRIPTION_CHANGE_ACTIVE_HOLDS"


class SubscriptionChangeAlreadyExists(SubscriptionChangeError):
    code = "SUBSCRIPTION_CHANGE_ALREADY_EXISTS"


class SubscriptionChangeIdempotencyConflict(SubscriptionChangeError):
    code = "SUBSCRIPTION_CHANGE_IDEMPOTENCY_CONFLICT"


class SubscriptionChangeStateConflict(SubscriptionChangeError):
    code = "SUBSCRIPTION_CHANGE_STATE_CONFLICT"


class SubscriptionChangeConfirmationRequired(SubscriptionChangeError):
    code = "SUBSCRIPTION_CHANGE_CONFIRMATION_REQUIRED"


@dataclass(frozen=True)
class ChangePreview:
    change_type: str
    target_plan_id: str
    target_plan_version_id: str
    source_plan_version_no: int
    target_plan_version_no: int
    quota_policy: str
    effective_at: object
    ends_at: object | None
    cycle_anchor_day: int
    cycle_anchor_time: object
    unavailable_confirmation_required: bool
    changed_limit_keys: tuple[str, ...]
    added_model_keys: tuple[str, ...]
    removed_model_keys: tuple[str, ...]
    active_count: int
    target_limit: int
    required_archive_count: int


def _benefit_values(snapshot):
    limits = snapshot.get("limits")
    if not isinstance(limits, dict):
        raise SubscriptionPlanVersionMismatch
    comparable = {}
    for key, value in limits.items():
        if isinstance(value, bool):
            comparable[f"limit:{key}"] = int(value)
        elif isinstance(value, int) and not isinstance(value, bool):
            comparable[f"limit:{key}"] = value
    models = snapshot.get("model_permissions")
    if not isinstance(models, list):
        raise SubscriptionPlanVersionMismatch
    enabled = {
        item.get("model_key") for item in models if isinstance(item, dict) and item.get("model_key")
    }
    return comparable, enabled


def classify_change(source: Subscription, target_version: PlanVersion, requested_type: str):
    source_values, source_models = _benefit_values(source.entitlement_snapshot)
    target_values, target_models = _benefit_values(target_version.effective_config)
    if source.is_trial:
        if requested_type != SubscriptionChange.ChangeType.TRIAL_CONVERSION:
            raise SubscriptionChangeClassificationInvalid
        return SubscriptionChange.ChangeType.TRIAL_CONVERSION
    if requested_type == SubscriptionChange.ChangeType.RENEWAL:
        if target_version.plan_id != source.plan_id:
            raise SubscriptionChangeClassificationInvalid
        return SubscriptionChange.ChangeType.RENEWAL
    keys = set(source_values) | set(target_values)
    directions = set()
    for key in keys:
        source_value = source_values.get(key, 0)
        target_value = target_values.get(key, 0)
        if target_value > source_value:
            directions.add("up")
        elif target_value < source_value:
            directions.add("down")
    if target_models - source_models:
        directions.add("up")
    if source_models - target_models:
        directions.add("down")
    if directions == {"up"}:
        calculated = SubscriptionChange.ChangeType.UPGRADE
    elif directions == {"down"}:
        calculated = SubscriptionChange.ChangeType.DOWNGRADE
    else:
        calculated = SubscriptionChange.ChangeType.REPLACEMENT
    if requested_type and requested_type != calculated:
        raise SubscriptionChangeClassificationInvalid
    return calculated


def preview_subscription_change(
    *,
    source: Subscription,
    target_version: PlanVersion,
    requested_type: str,
    quota_policy: str,
    now=None,
):
    if quota_policy not in SubscriptionChange.QuotaPolicy.values:
        raise SubscriptionChangePolicyInvalid
    if target_version.plan.is_trial or target_version.plan.status == Plan.Status.ARCHIVED:
        raise SubscriptionPlanUnavailable
    if target_version.plan.status not in (Plan.Status.PUBLISHED, Plan.Status.OFFLINE):
        raise SubscriptionPlanUnavailable
    if target_version.status not in (PlanVersion.Status.PUBLISHED, PlanVersion.Status.RETIRED):
        raise SubscriptionPlanVersionMismatch
    _validate_snapshot(target_version)
    change_type = classify_change(source, target_version, requested_type)
    moment = now or timezone.now()
    if change_type == SubscriptionChange.ChangeType.RENEWAL:
        effective_at = source.ends_at
        ends_at = None
    elif change_type == SubscriptionChange.ChangeType.TRIAL_CONVERSION:
        effective_at = moment
        ends_at = _ends_at(moment, target_version.valid_days)
    else:
        effective_at = moment
        ends_at = source.ends_at
        if ends_at <= moment:
            raise SubscriptionChangeStateConflict
    source_values, source_models = _benefit_values(source.entitlement_snapshot)
    target_values, target_models = _benefit_values(target_version.effective_config)
    from apps.subjects.subject_services import subject_limit_preview

    limit_preview = subject_limit_preview(
        user=source.user,
        target_snapshot=target_version.effective_config,
    )
    changed = tuple(
        sorted(
            key.removeprefix("limit:")
            for key in set(source_values) | set(target_values)
            if source_values.get(key) != target_values.get(key)
        )
    )
    return ChangePreview(
        change_type=change_type,
        target_plan_id=str(target_version.plan_id),
        target_plan_version_id=str(target_version.pk),
        source_plan_version_no=source.plan_version_no,
        target_plan_version_no=target_version.version_no,
        quota_policy=quota_policy,
        effective_at=effective_at,
        ends_at=ends_at,
        cycle_anchor_day=(
            timezone.localtime(moment).day
            if change_type == SubscriptionChange.ChangeType.TRIAL_CONVERSION
            else source.cycle_anchor_day
        ),
        cycle_anchor_time=(
            timezone.localtime(moment).timetz().replace(tzinfo=None)
            if change_type == SubscriptionChange.ChangeType.TRIAL_CONVERSION
            else source.cycle_anchor_time
        ),
        unavailable_confirmation_required=(
            target_version.plan.status == Plan.Status.OFFLINE
            or target_version.status == PlanVersion.Status.RETIRED
        ),
        changed_limit_keys=changed,
        added_model_keys=tuple(sorted(target_models - source_models)),
        removed_model_keys=tuple(sorted(source_models - target_models)),
        active_count=limit_preview.active_count,
        target_limit=limit_preview.target_limit,
        required_archive_count=limit_preview.required_archive_count,
    )


def scoped_subscription_changes(user, context: AdminContext):
    customer_ids = scoped_customers(user, context).values("pk")
    return (
        SubscriptionChange.objects.filter(user_id__in=customer_ids)
        .select_related(
            "user",
            "from_subscription",
            "target_plan",
            "target_plan_version",
            "requested_by",
        )
        .prefetch_related("events")
    )


def scoped_subscription_change_or_404(user, context, change_id, *, lock=False):
    query = scoped_subscription_changes(user, context)
    if lock:
        query = query.select_for_update(of=("self",))
    try:
        return query.get(pk=change_id)
    except SubscriptionChange.DoesNotExist as exc:
        raise NotFound from exc


def user_subscription_changes(user):
    return (
        SubscriptionChange.objects.filter(user=user)
        .select_related("from_subscription", "target_plan", "target_plan_version")
        .prefetch_related("events")
    )


def _assert_digest_match(change, digests: PlanChangeDigests):
    if (
        change.idempotency_key_version != digests.key_version
        or change.idempotency_scope_digest != digests.scope_digest
        or change.request_digest != digests.request_digest
    ):
        raise SubscriptionChangeIdempotencyConflict


def _assert_cancellation_digest_match(change, digests: PlanChangeDigests):
    if (
        change.cancellation_idempotency_key_version != digests.key_version
        or change.cancellation_idempotency_scope_digest != digests.scope_digest
        or change.cancellation_request_digest != digests.request_digest
    ):
        raise SubscriptionChangeIdempotencyConflict


def _event(change, event_type, from_status, actor, request_id):
    return SubscriptionChangeEvent.objects.create(
        change=change,
        event_type=event_type,
        from_status=from_status,
        to_status=change.status,
        actor=actor,
        safe_summary={
            "scheduled": "订阅续费已排期。",
            "executed": "订阅套餐变更已执行。",
            "cancelled": "订阅续费排期已取消。",
        }[event_type],
        request_id=request_id,
    )


def _validate_target(plan, version, *, confirm_unavailable, unavailable_reason):
    if plan.is_trial:
        raise SubscriptionPlanUnavailable
    if plan.status == Plan.Status.ARCHIVED:
        raise SubscriptionPlanUnavailable
    if plan.status not in (Plan.Status.PUBLISHED, Plan.Status.OFFLINE):
        raise SubscriptionPlanUnavailable
    if version.status not in (PlanVersion.Status.PUBLISHED, PlanVersion.Status.RETIRED):
        raise SubscriptionPlanVersionMismatch
    needs_confirmation = (
        plan.status == Plan.Status.OFFLINE or version.status == PlanVersion.Status.RETIRED
    )
    if needs_confirmation and not confirm_unavailable:
        raise SubscriptionChangeConfirmationRequired
    return normalize_note(unavailable_reason, required=needs_confirmation)


@transaction.atomic
def execute_subscription_change(
    *,
    requester,
    admin_context,
    source_subscription_id,
    expected_version,
    target_plan_id,
    target_plan_version_id,
    requested_type,
    quota_policy,
    confirm_unavailable,
    unavailable_reason,
    reason,
    digests: PlanChangeDigests,
    request_id,
    source_approval=None,
):
    existing = SubscriptionChange.objects.filter(idempotency_key_digest=digests.key_digest).first()
    if existing is not None:
        _assert_digest_match(existing, digests)
        return existing

    visible = (
        Subscription.objects.filter(
            pk=source_subscription_id,
            user_id__in=scoped_customers(requester, admin_context).values("pk"),
        )
        .only("pk")
        .first()
    )
    if visible is None:
        raise NotFound
    plan, target_version = _lock_plan_and_version(target_plan_id, target_plan_version_id)
    _validate_target(
        plan,
        target_version,
        confirm_unavailable=confirm_unavailable,
        unavailable_reason=unavailable_reason,
    )
    user_id = Subscription.objects.only("user_id").get(pk=source_subscription_id).user_id
    user = User.objects.select_for_update().get(pk=user_id)
    existing = SubscriptionChange.objects.filter(idempotency_key_digest=digests.key_digest).first()
    if existing is not None:
        _assert_digest_match(existing, digests)
        return existing
    source = (
        Subscription.objects.select_for_update()
        .select_related("plan", "plan_version")
        .get(pk=source_subscription_id, user=user)
    )
    if source.version != expected_version:
        raise SubscriptionVersionConflict
    if SubscriptionChange.objects.filter(
        from_subscription=source,
        status__in=(SubscriptionChange.Status.SCHEDULED, SubscriptionChange.Status.EXECUTED),
    ).exists():
        raise SubscriptionChangeAlreadyExists
    if (
        source.status != Subscription.Status.ACTIVE
        or not source.starts_at <= timezone.now() < source.ends_at
    ):
        raise SubscriptionChangeStateConflict

    snapshot, digest = _validate_snapshot(target_version)
    now = timezone.now()
    preview = preview_subscription_change(
        source=source,
        target_version=target_version,
        requested_type=requested_type,
        quota_policy=quota_policy,
        now=now,
    )
    if (
        preview.required_archive_count
        and preview.change_type != SubscriptionChange.ChangeType.RENEWAL
    ):
        raise SubscriptionSubjectLimitReconciliationRequired
    normalized_reason = normalize_note(reason, required=True)

    if preview.change_type == SubscriptionChange.ChangeType.RENEWAL:
        try:
            change = SubscriptionChange.objects.create(
                user=user,
                from_subscription=source,
                target_plan=plan,
                target_plan_version=target_version,
                target_plan_version_no=target_version.version_no,
                target_entitlement_digest=digest,
                status=SubscriptionChange.Status.SCHEDULED,
                change_type=preview.change_type,
                quota_policy=quota_policy,
                effective_at=source.ends_at,
                reason=normalized_reason,
                unavailable_reason=normalize_note(
                    unavailable_reason,
                    required=preview.unavailable_confirmation_required,
                ),
                requested_by=requester,
                idempotency_key_version=digests.key_version,
                source_approval=source_approval,
                next_attempt_at=source.ends_at,
                idempotency_key_digest=digests.key_digest,
                idempotency_scope_digest=digests.scope_digest,
                request_digest=digests.request_digest,
                request_id=request_id,
            )
        except IntegrityError as exc:
            existing = SubscriptionChange.objects.filter(
                idempotency_key_digest=digests.key_digest
            ).first()
            if existing is not None:
                _assert_digest_match(existing, digests)
                return existing
            raise SubscriptionChangeAlreadyExists from exc
        _event(
            change,
            SubscriptionChangeEvent.EventType.SCHEDULED,
            "",
            requester,
            request_id,
        )
        Notification.objects.create(
            recipient=user,
            notification_type=Notification.NotificationType.SUBSCRIPTION_TERMINATED,
            title="套餐续费已排期",
            safe_summary="您的套餐续费已安排在当前订阅结束时生效。",
            related_subscription=source,
        )
        return change

    if subscription_has_unsettled_holds(source):
        raise SubscriptionChangeActiveHolds
    if source.quota_accounts.filter(frozen__gt=0).exists():
        raise SubscriptionChangeActiveHolds

    change = SubscriptionChange.objects.create(
        user=user,
        from_subscription=source,
        target_plan=plan,
        target_plan_version=target_version,
        target_plan_version_no=target_version.version_no,
        target_entitlement_digest=digest,
        status=SubscriptionChange.Status.EXECUTED,
        change_type=preview.change_type,
        quota_policy=quota_policy,
        effective_at=now,
        reason=normalized_reason,
        unavailable_reason=normalize_note(
            unavailable_reason,
            required=preview.unavailable_confirmation_required,
        ),
        requested_by=requester,
        executed_at=now,
        idempotency_key_version=digests.key_version,
        idempotency_key_digest=digests.key_digest,
        idempotency_scope_digest=digests.scope_digest,
        request_digest=digests.request_digest,
        request_id=request_id,
    )
    source.status = Subscription.Status.TERMINATED
    source.terminated_at = now
    source.terminated_by = requester
    source.termination_reason = "套餐变更。"
    source.version += 1
    source.save(
        update_fields=[
            "status",
            "terminated_at",
            "terminated_by",
            "termination_reason",
            "version",
            "updated_at",
        ]
    )
    _subscription_event(
        subscription=source,
        event_type="terminated",
        from_status="active",
        actor=requester,
        request_id=request_id,
    )
    target = _create_active_subscription(
        user=user,
        application=None,
        plan=plan,
        version=target_version,
        actor=requester,
        opening_note=normalized_reason,
        request_id=request_id,
        now=now,
        source_change=change,
        ends_at=preview.ends_at,
        cycle_anchor_day=preview.cycle_anchor_day,
        cycle_anchor_time=(
            None
            if preview.change_type == SubscriptionChange.ChangeType.TRIAL_CONVERSION
            else source.cycle_anchor_time
        ),
    )
    try:
        apply_subscription_change_quotas(
            change=change,
            source_subscription=source,
            target_subscription=target,
            quota_policy=quota_policy,
            actor=requester,
            request_id=request_id,
            now=now,
        )
    except QuotaHoldStateConflict as exc:
        raise SubscriptionChangeActiveHolds from exc
    _event(
        change,
        SubscriptionChangeEvent.EventType.EXECUTED,
        "",
        requester,
        request_id,
    )
    Notification.objects.create(
        recipient=user,
        notification_type=Notification.NotificationType.SUBSCRIPTION_TERMINATED,
        title="套餐变更已生效",
        safe_summary="您的新套餐权益已生效。",
        related_subscription=target,
    )
    return change


@transaction.atomic
def cancel_scheduled_change(
    *,
    requester,
    admin_context,
    change_id,
    expected_version,
    reason,
    digests: PlanChangeDigests,
    request_id,
):
    existing = SubscriptionChange.objects.filter(
        cancellation_idempotency_key_digest=digests.key_digest
    ).first()
    if existing is not None:
        _assert_cancellation_digest_match(existing, digests)
        return existing
    change = scoped_subscription_change_or_404(
        requester,
        admin_context,
        change_id,
        lock=True,
    )
    if change.version != expected_version:
        raise SubscriptionVersionConflict
    if change.status != SubscriptionChange.Status.SCHEDULED:
        raise SubscriptionChangeStateConflict
    now = timezone.now()
    if now >= change.effective_at:
        raise SubscriptionChangeStateConflict
    previous = change.status
    change.status = SubscriptionChange.Status.CANCELLED
    change.cancelled_at = now
    change.cancelled_by = requester
    change.cancellation_reason = normalize_note(reason, required=True)
    change.version += 1
    change.cancellation_idempotency_key_version = digests.key_version
    change.cancellation_idempotency_key_digest = digests.key_digest
    change.cancellation_idempotency_scope_digest = digests.scope_digest
    change.cancellation_request_digest = digests.request_digest
    change.save(
        update_fields=[
            "status",
            "cancelled_at",
            "cancelled_by",
            "cancellation_reason",
            "version",
            "cancellation_idempotency_key_version",
            "cancellation_idempotency_key_digest",
            "cancellation_idempotency_scope_digest",
            "cancellation_request_digest",
            "updated_at",
        ]
    )
    _event(
        change,
        SubscriptionChangeEvent.EventType.CANCELLED,
        previous,
        requester,
        request_id,
    )
    Notification.objects.create(
        recipient=change.user,
        notification_type=Notification.NotificationType.SUBSCRIPTION_TERMINATED,
        title="套餐续费排期已取消",
        safe_summary="您的套餐续费排期已取消。",
        related_subscription=change.from_subscription,
    )
    return change
