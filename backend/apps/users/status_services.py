from dataclasses import dataclass
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied

from .models import Notification, User, UserStatusEvent
from .validators import validate_safe_plain_text


class AccountStateConflict(Exception):
    pass


@dataclass(frozen=True)
class StatusChangeResult:
    user: User
    event: UserStatusEvent


NOTIFICATION_TEMPLATES = {
    Notification.NotificationType.ACCOUNT_FROZEN: (
        "账号已禁用",
        "你的账号当前已被禁用，如有疑问请联系管理员。",
    ),
    Notification.NotificationType.ACCOUNT_UNFROZEN: (
        "账号已恢复",
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
    user.status_version += 1
    user.save(
        update_fields=[
            "account_status",
            "is_active",
            "session_version",
            "status_version",
            "updated_at",
        ]
    )
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
