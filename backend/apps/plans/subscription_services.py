import copy
import hashlib
import json
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.admin_rbac.permissions import AdminContext
from apps.admin_rbac.scopes import scoped_customer_or_404, scoped_customers
from apps.users.models import Notification, User

from .application_services import scoped_application_or_404
from .models import (
    Plan,
    PlanApplication,
    PlanApplicationEvent,
    PlanVersion,
    Subscription,
    SubscriptionEvent,
)


class SubscriptionError(Exception):
    pass


class SubscriptionNotEligible(SubscriptionError):
    code = "SUBSCRIPTION_NOT_ELIGIBLE"


class SubscriptionAlreadyActive(SubscriptionError):
    code = "SUBSCRIPTION_ALREADY_ACTIVE"


class SubscriptionStateConflict(SubscriptionError):
    code = "SUBSCRIPTION_STATE_CONFLICT"


class SubscriptionVersionConflict(SubscriptionError):
    code = "SUBSCRIPTION_VERSION_CONFLICT"


class SubscriptionPlanUnavailable(SubscriptionError):
    code = "SUBSCRIPTION_PLAN_UNAVAILABLE"


class SubscriptionPlanVersionMismatch(SubscriptionError):
    code = "SUBSCRIPTION_PLAN_VERSION_MISMATCH"


class SubscriptionTrialAlreadyGranted(SubscriptionError):
    code = "SUBSCRIPTION_TRIAL_ALREADY_GRANTED"


class SubscriptionConfirmationRequired(SubscriptionError):
    code = "SUBSCRIPTION_CONFIRMATION_REQUIRED"


class SubscriptionOverrideForbidden(SubscriptionError):
    code = "SUBSCRIPTION_OVERRIDE_FORBIDDEN"


class SubscriptionNoteInvalid(SubscriptionError):
    code = "SUBSCRIPTION_NOTE_INVALID"


def normalize_note(value: str, *, required: bool = False) -> str:
    note = (value or "").strip()
    if len(note) > 500 or (required and not note):
        raise SubscriptionNoteInvalid
    return note


def _ensure_user_eligible(user: User) -> None:
    if (
        not user.is_active
        or user.account_status != User.AccountStatus.ACTIVE
        or user.approval_status != User.ApprovalStatus.APPROVED
        or user.is_staff
        or user.is_superuser
        or hasattr(user, "admin_profile")
    ):
        raise SubscriptionNotEligible


def _snapshot_digest(snapshot) -> str:
    encoded = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _lock_plan_and_version(plan_id, version_id) -> tuple[Plan, PlanVersion]:
    try:
        plan = Plan.objects.select_for_update().get(pk=plan_id)
    except Plan.DoesNotExist as exc:
        raise SubscriptionPlanUnavailable from exc
    try:
        version = PlanVersion.objects.select_for_update().get(pk=version_id, plan=plan)
    except PlanVersion.DoesNotExist as exc:
        raise SubscriptionPlanVersionMismatch from exc
    return plan, version


def _validate_snapshot(version: PlanVersion) -> tuple[dict, str]:
    if not version.effective_config or not version.config_digest:
        raise SubscriptionPlanVersionMismatch
    snapshot = copy.deepcopy(version.effective_config)
    if _snapshot_digest(snapshot) != version.config_digest:
        raise SubscriptionPlanVersionMismatch
    if (
        snapshot.get("plan_version_id") != str(version.pk)
        or snapshot.get("plan_id") != str(version.plan_id)
        or snapshot.get("version_no") != version.version_no
        or snapshot.get("valid_days") != version.valid_days
    ):
        raise SubscriptionPlanVersionMismatch
    return snapshot, version.config_digest


def _ends_at(starts_at, valid_days: int):
    local_start = timezone.localtime(starts_at)
    return (local_start + timedelta(days=valid_days)).astimezone(starts_at.tzinfo)


def _subscription_event(
    *,
    subscription,
    event_type,
    from_status,
    actor,
    request_id,
):
    summaries = {
        SubscriptionEvent.EventType.ACTIVATED: "套餐订阅已生效。",
        SubscriptionEvent.EventType.EXPIRED: "套餐订阅已到期。",
        SubscriptionEvent.EventType.TERMINATED: "套餐订阅已终止。",
    }
    return SubscriptionEvent.objects.create(
        subscription=subscription,
        event_type=event_type,
        from_status=from_status,
        to_status=subscription.status,
        actor=actor,
        safe_summary=summaries[event_type],
        request_id=request_id,
    )


def _notify(
    *,
    subscription,
    notification_type,
    title,
    summary,
    application=None,
):
    return Notification.objects.create(
        recipient=subscription.user,
        notification_type=notification_type,
        title=title,
        safe_summary=summary,
        related_plan_application=application,
        related_subscription=subscription,
    )


def _expire_stale_active(*, user: User, now, request_id) -> None:
    active = (
        Subscription.objects.select_for_update()
        .filter(user=user, status=Subscription.Status.ACTIVE)
        .first()
    )
    if active is None:
        return
    if active.ends_at > now:
        raise SubscriptionAlreadyActive
    active.status = Subscription.Status.EXPIRED
    active.expired_at = now
    active.version += 1
    active.save(update_fields=["status", "expired_at", "version", "updated_at"])
    _subscription_event(
        subscription=active,
        event_type=SubscriptionEvent.EventType.EXPIRED,
        from_status=Subscription.Status.ACTIVE,
        actor=None,
        request_id=request_id,
    )
    _notify(
        subscription=active,
        notification_type=Notification.NotificationType.SUBSCRIPTION_EXPIRED,
        title="套餐已到期",
        summary="您的套餐订阅已到期。",
    )


def _create_active_subscription(
    *,
    user,
    application,
    plan,
    version,
    actor,
    opening_note,
    request_id,
    now,
):
    snapshot, digest = _validate_snapshot(version)
    ends_at = _ends_at(now, version.valid_days)
    try:
        with transaction.atomic():
            subscription = Subscription.objects.create(
                user=user,
                source_application=application,
                plan=plan,
                plan_version=version,
                plan_version_no=version.version_no,
                entitlement_snapshot=snapshot,
                entitlement_digest=digest,
                status=Subscription.Status.ACTIVE,
                starts_at=now,
                ends_at=ends_at,
                cycle_anchor_day=timezone.localtime(now).day,
                is_trial=plan.is_trial,
                opened_by=actor,
                opening_note=opening_note,
                activated_at=now,
                request_id=request_id,
            )
    except IntegrityError as exc:
        if Subscription.objects.filter(user=user, status=Subscription.Status.ACTIVE).exists():
            raise SubscriptionAlreadyActive from exc
        if plan.is_trial and Subscription.objects.filter(user=user, is_trial=True).exists():
            raise SubscriptionTrialAlreadyGranted from exc
        raise SubscriptionStateConflict from exc
    _subscription_event(
        subscription=subscription,
        event_type=SubscriptionEvent.EventType.ACTIVATED,
        from_status="",
        actor=actor,
        request_id=request_id,
    )
    return subscription


def current_subscription(user: User, *, now=None):
    moment = now or timezone.now()
    return (
        Subscription.objects.filter(
            user=user,
            status=Subscription.Status.ACTIVE,
            starts_at__lte=moment,
            ends_at__gt=moment,
        )
        .select_related("plan", "plan_version")
        .prefetch_related("events")
        .first()
    )


def scoped_subscriptions(user, context: AdminContext):
    customer_ids = scoped_customers(user, context).values("pk")
    return (
        Subscription.objects.filter(user_id__in=customer_ids)
        .select_related(
            "user",
            "plan",
            "plan_version",
            "source_application",
            "user__customer_assignment__owner_admin__user",
        )
        .prefetch_related("events")
    )


def scoped_subscription_or_404(user, context, subscription_id, *, lock=False):
    query = scoped_subscriptions(user, context)
    if lock:
        query = query.select_for_update(of=("self",))
    try:
        return query.get(pk=subscription_id)
    except Subscription.DoesNotExist as exc:
        raise NotFound from exc


@transaction.atomic
def activate_application(
    *,
    requester,
    admin_context: AdminContext,
    application_id,
    expected_version: int,
    selected_plan_version_id,
    confirm_unavailable: bool,
    unavailable_reason: str,
    confirm_version_override: bool,
    override_reason: str,
    opening_note: str,
    request_id,
):
    application = scoped_application_or_404(requester, admin_context, application_id, lock=True)
    if application.version != expected_version:
        raise SubscriptionVersionConflict
    if application.status not in PlanApplication.OPEN_STATUSES:
        raise SubscriptionStateConflict
    user = User.objects.select_for_update().get(pk=application.applicant_id)
    _ensure_user_eligible(user)
    now = timezone.now()
    _expire_stale_active(user=user, now=now, request_id=request_id)

    selected_id = selected_plan_version_id or application.requested_plan_version_id
    is_override = selected_id != application.requested_plan_version_id
    override_note = normalize_note(override_reason, required=is_override)
    if is_override:
        if (
            "subscriptions.override_version" not in admin_context.permission_keys
            or not confirm_version_override
        ):
            raise SubscriptionOverrideForbidden
    plan, version = _lock_plan_and_version(application.plan_id, selected_id)
    if plan.is_trial:
        raise SubscriptionPlanUnavailable
    if plan.status not in (Plan.Status.PUBLISHED, Plan.Status.OFFLINE):
        raise SubscriptionPlanUnavailable
    if plan.status == Plan.Status.ARCHIVED:
        raise SubscriptionPlanUnavailable
    if version.status not in (PlanVersion.Status.PUBLISHED, PlanVersion.Status.RETIRED):
        raise SubscriptionPlanVersionMismatch
    needs_unavailable_confirmation = (
        plan.status == Plan.Status.OFFLINE or version.status == PlanVersion.Status.RETIRED
    )
    if needs_unavailable_confirmation and not confirm_unavailable:
        raise SubscriptionConfirmationRequired
    unavailable_note = normalize_note(unavailable_reason, required=needs_unavailable_confirmation)
    if not is_override and (
        version.pk != application.requested_plan_version_id
        or version.config_digest != application.requested_config_digest
    ):
        raise SubscriptionPlanVersionMismatch
    note = normalize_note(opening_note)
    subscription = _create_active_subscription(
        user=user,
        application=application,
        plan=plan,
        version=version,
        actor=requester,
        opening_note=note,
        request_id=request_id,
        now=now,
    )
    previous = application.status
    application.status = PlanApplication.Status.ACTIVATED
    application.activated_at = now
    application.activated_by = requester
    application.version += 1
    application.save(
        update_fields=["status", "activated_at", "activated_by", "version", "updated_at"]
    )
    PlanApplicationEvent.objects.create(
        application=application,
        event_type=PlanApplicationEvent.EventType.ACTIVATED,
        from_status=previous,
        to_status=application.status,
        actor=requester,
        safe_summary="套餐申请已开通。",
        request_id=request_id,
    )
    _notify(
        subscription=subscription,
        notification_type=Notification.NotificationType.PLAN_APPLICATION_ACTIVATED,
        title="套餐已开通",
        summary="您的套餐申请已完成开通。",
        application=application,
    )
    return (
        subscription,
        application,
        {
            "version_override": is_override,
            "override_reason_recorded": bool(override_note),
            "unavailable_confirmation": needs_unavailable_confirmation,
            "unavailable_reason_recorded": bool(unavailable_note),
        },
    )


@transaction.atomic
def grant_trial(
    *,
    requester,
    admin_context: AdminContext,
    user_id,
    expected_status_version: int,
    plan_id,
    opening_note: str,
    request_id,
):
    scoped_customer_or_404(requester, admin_context, user_id)
    user = User.objects.select_for_update().get(pk=user_id)
    if user.status_version != expected_status_version:
        raise SubscriptionVersionConflict
    _ensure_user_eligible(user)
    now = timezone.now()
    _expire_stale_active(user=user, now=now, request_id=request_id)
    if Subscription.objects.filter(user=user, is_trial=True).exists():
        raise SubscriptionTrialAlreadyGranted
    try:
        plan = Plan.objects.select_for_update().get(pk=plan_id)
    except Plan.DoesNotExist as exc:
        raise SubscriptionPlanUnavailable from exc
    if (
        not plan.is_trial
        or plan.status != Plan.Status.PUBLISHED
        or plan.current_published_version_id is None
    ):
        raise SubscriptionPlanUnavailable
    try:
        version = PlanVersion.objects.select_for_update().get(
            pk=plan.current_published_version_id,
            plan=plan,
            status=PlanVersion.Status.PUBLISHED,
        )
    except PlanVersion.DoesNotExist as exc:
        raise SubscriptionPlanVersionMismatch from exc
    subscription = _create_active_subscription(
        user=user,
        application=None,
        plan=plan,
        version=version,
        actor=requester,
        opening_note=normalize_note(opening_note),
        request_id=request_id,
        now=now,
    )
    _notify(
        subscription=subscription,
        notification_type=Notification.NotificationType.SUBSCRIPTION_TRIAL_GRANTED,
        title="试用套餐已发放",
        summary="您的试用套餐已生效。",
    )
    return subscription


@transaction.atomic
def terminate_subscription(
    *,
    requester,
    admin_context: AdminContext,
    subscription_id,
    expected_version: int,
    reason: str,
    request_id,
):
    subscription = scoped_subscription_or_404(requester, admin_context, subscription_id, lock=True)
    if subscription.version != expected_version:
        raise SubscriptionVersionConflict
    if subscription.status != Subscription.Status.ACTIVE:
        raise SubscriptionStateConflict
    now = timezone.now()
    subscription.status = Subscription.Status.TERMINATED
    subscription.terminated_at = now
    subscription.terminated_by = requester
    subscription.termination_reason = normalize_note(reason, required=True)
    subscription.version += 1
    subscription.save(
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
        subscription=subscription,
        event_type=SubscriptionEvent.EventType.TERMINATED,
        from_status=Subscription.Status.ACTIVE,
        actor=requester,
        request_id=request_id,
    )
    _notify(
        subscription=subscription,
        notification_type=Notification.NotificationType.SUBSCRIPTION_TERMINATED,
        title="套餐已终止",
        summary="您的套餐订阅已由管理员终止。",
    )
    return subscription
