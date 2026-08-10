import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.admin_rbac.audit_services import validate_safe_json
from apps.admin_rbac.models import ApprovalRequest, AuditEvent
from apps.admin_rbac.risk_services import canonical_payload
from apps.quotas.lifecycle import (
    apply_expiry_dispositions,
    catch_up_subscription_cycles,
    expiry_policy_map,
)
from apps.quotas.services import apply_subscription_change_quotas, subscription_has_unsettled_holds
from apps.users.models import Notification, User

from .models import Plan, PlanVersion, Subscription, SubscriptionChange, SubscriptionChangeEvent
from .subscription_services import (
    SubscriptionEvent,
    _create_active_subscription,
    _ends_at,
    _lock_plan_and_version,
    _notify,
    _subscription_event,
    _validate_snapshot,
)

logger = logging.getLogger(__name__)
RENEWAL_BLOCKED_BY_HOLD = "RENEWAL_BLOCKED_BY_HOLD"
RENEWAL_WINDOW_ELAPSED = "RENEWAL_WINDOW_ELAPSED"
RENEWAL_SOURCE_TERMINATED = "RENEWAL_SOURCE_TERMINATED"
RENEWAL_PLAN_ARCHIVED = "RENEWAL_PLAN_ARCHIVED"
RENEWAL_CONFIRMATION_INVALID = "RENEWAL_CONFIRMATION_INVALID"
RENEWAL_DIGEST_MISMATCH = "RENEWAL_DIGEST_MISMATCH"
RENEWAL_APPROVAL_INVALID = "RENEWAL_APPROVAL_INVALID"


def _audit(
    *,
    action_key,
    outcome,
    target_id,
    request_id,
    subject=None,
    approval=None,
    safe_after=None,
    stable_error_code="",
):
    return AuditEvent.objects.create(
        category="subscription_lifecycle",
        action_key=action_key,
        outcome=outcome,
        actor=None,
        subject=subject,
        requester=approval.requester if approval else None,
        approver=approval.approved_by if approval else None,
        target_type="subscription_change" if approval else "subscription",
        target_id=target_id,
        request_id=request_id,
        approval_request=approval,
        safe_before={},
        safe_after=validate_safe_json(safe_after or {}),
        stable_error_code=stable_error_code,
    )


def _approval_payload(change):
    approval = change.source_approval
    if (
        approval is None
        or approval.action_key != "subscription.change"
        or approval.status != ApprovalRequest.Status.EXECUTED
        or (approval.execution_result or {}).get("change_id") != str(change.pk)
    ):
        raise ValueError(RENEWAL_APPROVAL_INVALID)
    payload, digest = canonical_payload(
        approval.action_key,
        approval.target_type,
        approval.target_id,
        approval.target_version,
        approval.sanitized_payload,
    )
    if digest != approval.payload_digest:
        raise ValueError(RENEWAL_DIGEST_MISMATCH)
    expected = {
        "target_plan_version_id": str(change.target_plan_version_id),
        "change_type": SubscriptionChange.ChangeType.RENEWAL,
        "quota_policy": change.quota_policy,
        "request_digest": change.request_digest,
    }
    if any(str(payload.get(key)) != str(value) for key, value in expected.items()):
        raise ValueError(RENEWAL_DIGEST_MISMATCH)
    return approval, payload


def _change_event(change, event_type, from_status, request_id, summary):
    return SubscriptionChangeEvent.objects.create(
        change=change,
        event_type=event_type,
        from_status=from_status,
        to_status=change.status,
        actor=None,
        safe_summary=summary,
        request_id=request_id,
    )


def _mark_failed_locked(change, code, request_id):
    if change.status != SubscriptionChange.Status.SCHEDULED:
        return change
    previous = change.status
    change.status = SubscriptionChange.Status.FAILED
    change.failed_at = timezone.now()
    change.stable_error_code = code
    change.next_attempt_at = None
    change.version += 1
    change.save(
        update_fields=[
            "status",
            "failed_at",
            "stable_error_code",
            "next_attempt_at",
            "version",
            "updated_at",
        ]
    )
    _change_event(
        change,
        SubscriptionChangeEvent.EventType.FAILED,
        previous,
        request_id,
        "Scheduled renewal failed permanently.",
    )
    _audit(
        action_key="subscription.renewal.execute",
        outcome="failed",
        target_id=change.pk,
        request_id=request_id,
        subject=change.user,
        approval=change.source_approval,
        safe_after={"status": "failed"},
        stable_error_code=code,
    )
    if code == RENEWAL_DIGEST_MISMATCH:
        logger.critical(
            "scheduled renewal immutable digest mismatch",
            extra={"request_id": str(request_id), "exception_type": code},
        )
    return change


def _fail_expired_renewal_locked(change, code, request_id):
    failed = _mark_failed_locked(change, code, request_id)
    apply_expiry_dispositions(subscription_id=change.from_subscription_id, request_id=request_id)
    return failed


@transaction.atomic
def expire_subscription(*, subscription_id, request_id, now=None):
    moment = now or timezone.now()
    user_id = Subscription.objects.only("user_id").get(pk=subscription_id).user_id
    User.objects.select_for_update().get(pk=user_id)
    subscription = Subscription.objects.select_for_update().get(pk=subscription_id)
    if subscription.status == Subscription.Status.TERMINATED:
        return subscription
    if subscription.status == Subscription.Status.ACTIVE:
        if subscription.ends_at > moment:
            return subscription
        subscription.status = Subscription.Status.EXPIRED
        subscription.expired_at = subscription.ends_at
        subscription.version += 1
        subscription.save(update_fields=["status", "expired_at", "version", "updated_at"])
        _subscription_event(
            subscription=subscription,
            event_type=SubscriptionEvent.EventType.EXPIRED,
            from_status=Subscription.Status.ACTIVE,
            actor=None,
            request_id=request_id,
        )
        _notify(
            subscription=subscription,
            notification_type=Notification.NotificationType.SUBSCRIPTION_EXPIRED,
            title="Subscription expired",
            summary="Your subscription has expired.",
        )
        _audit(
            action_key="subscription.expire",
            outcome="executed",
            target_id=subscription.pk,
            request_id=request_id,
            subject=subscription.user,
            safe_after={"status": "expired", "version": subscription.version},
        )
    pending_renewal = SubscriptionChange.objects.filter(
        from_subscription=subscription,
        change_type=SubscriptionChange.ChangeType.RENEWAL,
        status=SubscriptionChange.Status.SCHEDULED,
    ).exists()
    if not pending_renewal:
        apply_expiry_dispositions(subscription_id=subscription.pk, request_id=request_id)
    return subscription


def _retry_blocked_locked(change, now):
    change.retry_count += 1
    delay = min(3600, 60 * (2 ** min(change.retry_count - 1, 6)))
    change.next_attempt_at = now + timedelta(seconds=delay)
    change.stable_error_code = RENEWAL_BLOCKED_BY_HOLD
    change.save(update_fields=["retry_count", "next_attempt_at", "stable_error_code", "updated_at"])
    if change.retry_count in (5, 10, 20):
        logger.error(
            "scheduled renewal remains blocked",
            extra={"request_id": str(change.request_id), "exception_type": RENEWAL_BLOCKED_BY_HOLD},
        )
    return change


def execute_due_renewal(*, change_id, request_id, now=None):
    moment = now or timezone.now()
    binding = SubscriptionChange.objects.only(
        "target_plan_id", "target_plan_version_id", "from_subscription_id"
    ).get(pk=change_id)
    expire_subscription(
        subscription_id=binding.from_subscription_id, request_id=request_id, now=moment
    )
    with transaction.atomic():
        plan, version = _lock_plan_and_version(
            binding.target_plan_id, binding.target_plan_version_id
        )
        user_id = Subscription.objects.only("user_id").get(pk=binding.from_subscription_id).user_id
        user = User.objects.select_for_update().get(pk=user_id)
        source = Subscription.objects.select_for_update().get(pk=binding.from_subscription_id)
        change = (
            SubscriptionChange.objects.select_for_update(of=("self",))
            .select_related(
                "source_approval", "source_approval__requester", "source_approval__approved_by"
            )
            .get(pk=change_id)
        )
        if change.status != SubscriptionChange.Status.SCHEDULED:
            return change
        if change.effective_at > moment or (
            change.next_attempt_at is not None and change.next_attempt_at > moment
        ):
            return change
        if source.status == Subscription.Status.TERMINATED:
            return _mark_failed_locked(change, RENEWAL_SOURCE_TERMINATED, request_id)
        try:
            approval, payload = _approval_payload(change)
        except ValueError as exc:
            code = (
                str(exc)
                if str(exc) in {RENEWAL_APPROVAL_INVALID, RENEWAL_DIGEST_MISMATCH}
                else RENEWAL_APPROVAL_INVALID
            )
            return _fail_expired_renewal_locked(change, code, request_id)
        if plan.status == Plan.Status.ARCHIVED:
            return _fail_expired_renewal_locked(change, RENEWAL_PLAN_ARCHIVED, request_id)
        confirmed = bool(payload.get("confirm_unavailable")) and bool(
            payload.get("unavailable_reason")
        )
        if (
            plan.status == Plan.Status.OFFLINE or version.status == PlanVersion.Status.RETIRED
        ) and not confirmed:
            return _fail_expired_renewal_locked(change, RENEWAL_CONFIRMATION_INVALID, request_id)
        try:
            _snapshot, digest = _validate_snapshot(version)
        except Exception:
            return _fail_expired_renewal_locked(change, RENEWAL_DIGEST_MISMATCH, request_id)
        if digest != change.target_entitlement_digest:
            return _fail_expired_renewal_locked(change, RENEWAL_DIGEST_MISMATCH, request_id)
        target_ends_at = _ends_at(change.effective_at, version.valid_days)
        if target_ends_at <= moment:
            return _fail_expired_renewal_locked(change, RENEWAL_WINDOW_ELAPSED, request_id)
        if (
            subscription_has_unsettled_holds(source)
            or source.quota_accounts.filter(frozen__gt=0).exists()
        ):
            return _retry_blocked_locked(change, moment)
        previous = change.status
        change.status = SubscriptionChange.Status.EXECUTED
        change.executed_at = moment
        change.next_attempt_at = None
        change.stable_error_code = ""
        change.version += 1
        change.save(
            update_fields=[
                "status",
                "executed_at",
                "next_attempt_at",
                "stable_error_code",
                "version",
                "updated_at",
            ]
        )
        target = _create_active_subscription(
            user=user,
            application=None,
            plan=plan,
            version=version,
            actor=None,
            opening_note=change.reason,
            request_id=request_id,
            now=change.effective_at,
            source_change=change,
            ends_at=target_ends_at,
            cycle_anchor_day=source.cycle_anchor_day,
            cycle_anchor_time=source.cycle_anchor_time,
        )
        policies = expiry_policy_map(source)
        apply_subscription_change_quotas(
            change=change,
            source_subscription=source,
            target_subscription=target,
            quota_policy=change.quota_policy,
            expiry_policies=policies,
            actor=None,
            request_id=request_id,
            now=moment,
        )
        catch_up_subscription_cycles(
            subscription_id=target.pk,
            request_id=request_id,
            now=moment,
        )
        apply_expiry_dispositions(
            subscription_id=source.pk, request_id=request_id, renewal_change_id=change.pk
        )
        _change_event(
            change,
            SubscriptionChangeEvent.EventType.EXECUTED,
            previous,
            request_id,
            "Scheduled renewal executed.",
        )
        Notification.objects.create(
            recipient=user,
            notification_type=Notification.NotificationType.SUBSCRIPTION_RENEWED,
            title="Subscription renewed",
            safe_summary="Your scheduled renewal is active.",
            related_subscription=target,
        )
        _audit(
            action_key="subscription.renewal.execute",
            outcome="executed",
            target_id=change.pk,
            request_id=request_id,
            subject=user,
            approval=approval,
            safe_after={"status": "executed", "subscription_id": str(target.pk)},
        )
        return change


def due_renewal_ids(*, now=None, limit=100):
    moment = now or timezone.now()
    return list(
        SubscriptionChange.objects.filter(
            status=SubscriptionChange.Status.SCHEDULED,
            change_type=SubscriptionChange.ChangeType.RENEWAL,
            effective_at__lte=moment,
            next_attempt_at__lte=moment,
        )
        .order_by("effective_at", "id")
        .values_list("id", flat=True)[:limit]
    )


def due_expiry_ids(*, now=None, limit=100):
    moment = now or timezone.now()
    return list(
        Subscription.objects.filter(status=Subscription.Status.ACTIVE, ends_at__lte=moment)
        .order_by("ends_at", "id")
        .values_list("id", flat=True)[:limit]
    )
