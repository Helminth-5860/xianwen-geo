from dataclasses import dataclass
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied

from .models import Notification, User, UserStatusEvent
from .validators import validate_nickname, validate_safe_plain_text


class ApprovalStateConflict(Exception):
    pass


class AccountStateConflict(Exception):
    pass


class ApprovalReasonRequired(Exception):
    pass


@dataclass(frozen=True)
class StatusChangeResult:
    user: User
    event: UserStatusEvent


NOTIFICATION_TEMPLATES = {
    Notification.NotificationType.APPROVAL_APPROVED: (
        "审核已通过",
        "你的账号审核已通过，可以继续使用已开放的功能。",
    ),
    Notification.NotificationType.APPROVAL_REJECTED: (
        "审核未通过",
        "请查看当前审核状态并完善资料后重新提交。",
    ),
    Notification.NotificationType.ACCOUNT_FROZEN: (
        "账号已冻结",
        "你的账号当前已被冻结，如有疑问请联系管理员。",
    ),
    Notification.NotificationType.ACCOUNT_UNFROZEN: (
        "账号已解冻",
        "你的账号已恢复使用，请重新登录。",
    ),
}


def _locked_active_staff(actor_id, permission_key: str) -> User:
    try:
        actor = User.objects.select_for_update().get(pk=actor_id)
    except User.DoesNotExist as exc:
        raise PermissionDenied from exc
    if not actor.is_active or not actor.is_staff:
        raise PermissionDenied
    from apps.admin_rbac.permissions import resolve_admin_context

    context = resolve_admin_context(actor)
    if context is None or (
        not actor.is_superuser and permission_key not in context.permission_keys
    ):
        raise PermissionDenied
    return actor


def _locked_target(user_id) -> User:
    try:
        return User.objects.select_for_update().get(pk=user_id)
    except User.DoesNotExist as exc:
        raise NotFound from exc


def _ensure_business_target(user: User) -> None:
    if user.is_staff or user.is_superuser:
        raise PermissionDenied


def _create_event(
    *,
    user: User,
    domain: str,
    event_type: str,
    from_value: str,
    to_value: str,
    reason: str,
    actor: User,
    request_id: UUID | str,
) -> UserStatusEvent:
    return UserStatusEvent.objects.create(
        user=user,
        status_domain=domain,
        event_type=event_type,
        from_value=from_value,
        to_value=to_value,
        reason=reason,
        actor=actor,
        request_id=request_id,
    )


def _create_notification(
    *,
    recipient: User,
    notification_type: Notification.NotificationType,
    event: UserStatusEvent,
) -> Notification:
    title, safe_summary = NOTIFICATION_TEMPLATES[notification_type]
    return Notification.objects.create(
        recipient=recipient,
        notification_type=notification_type,
        title=title,
        safe_summary=safe_summary,
        related_status_event=event,
    )


@transaction.atomic
def review_user(
    *,
    actor_id,
    user_id,
    decision: str,
    reason: str,
    request_id: UUID | str,
) -> StatusChangeResult:
    actor = _locked_active_staff(actor_id, "users.review")
    user = _locked_target(user_id)
    _ensure_business_target(user)
    if user.approval_status != User.ApprovalStatus.PENDING:
        raise ApprovalStateConflict

    from_value = user.approval_status
    if decision == "approve":
        user.approval_status = User.ApprovalStatus.APPROVED
        user.approval_reason = ""
        user.approved_at = timezone.now()
        user.approved_by = actor
        event_type = UserStatusEvent.EventType.APPROVED
        notification_type = Notification.NotificationType.APPROVAL_APPROVED
        clean_reason = ""
    elif decision == "reject":
        if not reason.strip():
            raise ApprovalReasonRequired
        clean_reason = validate_safe_plain_text(
            reason,
            field_label="拒绝原因",
            max_length=500,
            required=True,
        )
        user.approval_status = User.ApprovalStatus.REJECTED
        user.approval_reason = clean_reason
        user.approved_at = None
        user.approved_by = None
        event_type = UserStatusEvent.EventType.REJECTED
        notification_type = Notification.NotificationType.APPROVAL_REJECTED
    else:
        raise ApprovalStateConflict

    user.save(
        update_fields=[
            "approval_status",
            "approval_reason",
            "approved_at",
            "approved_by",
            "updated_at",
        ]
    )
    event = _create_event(
        user=user,
        domain=UserStatusEvent.StatusDomain.APPROVAL,
        event_type=event_type,
        from_value=from_value,
        to_value=user.approval_status,
        reason=clean_reason,
        actor=actor,
        request_id=request_id,
    )
    _create_notification(recipient=user, notification_type=notification_type, event=event)
    return StatusChangeResult(user=user, event=event)


@transaction.atomic
def resubmit_approval(
    *,
    user_id,
    nickname: str | None,
    request_id: UUID | str,
) -> StatusChangeResult:
    user = _locked_target(user_id)
    if user.approval_status != User.ApprovalStatus.REJECTED:
        raise ApprovalStateConflict
    from_value = user.approval_status
    update_fields = ["approval_status", "approval_reason", "updated_at"]
    if nickname is not None:
        user.nickname = validate_nickname(nickname)
        update_fields.append("nickname")
    user.approval_status = User.ApprovalStatus.PENDING
    user.approval_reason = ""
    user.save(update_fields=update_fields)
    event = _create_event(
        user=user,
        domain=UserStatusEvent.StatusDomain.APPROVAL,
        event_type=UserStatusEvent.EventType.RESUBMITTED,
        from_value=from_value,
        to_value=user.approval_status,
        reason="",
        actor=user,
        request_id=request_id,
    )
    return StatusChangeResult(user=user, event=event)


@transaction.atomic
def change_account_status(
    *,
    actor_id,
    user_id,
    action: str,
    reason: str,
    request_id: UUID | str,
) -> StatusChangeResult:
    actor = _locked_active_staff(actor_id, "users.freeze")
    user = _locked_target(user_id)
    _ensure_business_target(user)
    clean_reason = validate_safe_plain_text(
        reason,
        field_label="操作原因",
        max_length=500,
        required=False,
    )
    from_value = user.account_status
    if action == "freeze" and from_value == User.AccountStatus.ACTIVE:
        user.account_status = User.AccountStatus.FROZEN
        user.is_active = False
        user.session_version += 1
        event_type = UserStatusEvent.EventType.FROZEN
        notification_type = Notification.NotificationType.ACCOUNT_FROZEN
    elif action == "unfreeze" and from_value == User.AccountStatus.FROZEN:
        user.account_status = User.AccountStatus.ACTIVE
        user.is_active = True
        event_type = UserStatusEvent.EventType.UNFROZEN
        notification_type = Notification.NotificationType.ACCOUNT_UNFROZEN
    else:
        raise AccountStateConflict
    user.save(update_fields=["account_status", "is_active", "session_version", "updated_at"])
    event = _create_event(
        user=user,
        domain=UserStatusEvent.StatusDomain.ACCOUNT,
        event_type=event_type,
        from_value=from_value,
        to_value=user.account_status,
        reason=clean_reason,
        actor=actor,
        request_id=request_id,
    )
    _create_notification(recipient=user, notification_type=notification_type, event=event)
    return StatusChangeResult(user=user, event=event)


@transaction.atomic
def mark_notification_read(*, user_id, notification_id) -> Notification:
    try:
        notification = Notification.objects.select_for_update().get(
            pk=notification_id,
            recipient_id=user_id,
        )
    except Notification.DoesNotExist as exc:
        raise NotFound from exc
    if notification.read_at is None:
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at"])
    return notification
