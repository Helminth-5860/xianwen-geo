from datetime import timedelta
from typing import Any

from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.utils import timezone

from apps.core.request_ids import validate_request_id
from apps.users.models import User
from apps.users.services import client_ip_address, request_user_agent

from .audit_services import validate_safe_json
from .sensitive_audit_models import SensitiveAuditLog

RETENTION_DAYS = 365
DEFAULT_PURGE_BATCH_SIZE = 5_000
DEFAULT_PURGE_MAX_BATCHES = 200

SENSITIVE_ACTION_KEYS = frozenset(
    {
        "admin.disable",
        "admin.lock",
        "admin.role.change",
        "admin.force_logout",
        "role.permissions.replace",
        "role.disable",
        "role.security.update",
        "role.ip_allowlist.update",
        "superuser.ip_allowlist.update",
        "customer.assignment.change",
        "user.freeze",
        "quota.grant",
        "quota.compensate",
        "quota.manual_deduct",
        "subscription.open",
        "subscription.grant_trial",
        "subscription.terminate",
        "subscription.change",
        "subscription.change.cancel",
    }
)

QUOTA_ACTION_SIGNS = {
    "quota.grant": 1,
    "quota.compensate": 1,
    "quota.manual_deduct": -1,
}


def is_sensitive_action(action_key: str) -> bool:
    return action_key in SENSITIVE_ACTION_KEYS


def _actor_role(user: User | None) -> str:
    if user is None:
        return "系统"
    if user.is_superuser:
        return "超级管理员"
    try:
        profile = user.admin_profile
    except ObjectDoesNotExist:
        return "管理员" if user.is_staff else "用户"
    if profile.role_id and profile.role:
        return profile.role.name
    return "管理员" if user.is_staff else "用户"


def _user_snapshot(user: User | None) -> dict[str, Any]:
    if user is None:
        return {
            "id": None,
            "name": "",
            "tenant_id": None,
            "tenant_name": "",
        }
    tenant = user.tenant
    return {
        "id": user.pk,
        "name": user.nickname,
        "tenant_id": tenant.pk if tenant else None,
        "tenant_name": tenant.display_name if tenant else "",
    }


def _owner_snapshot(user: User | None) -> dict[str, Any]:
    if user is None or user.is_staff or user.is_superuser:
        return {"id": None, "name": ""}
    try:
        assignment = user.customer_assignment
    except ObjectDoesNotExist:
        return {"id": None, "name": ""}
    owner = assignment.owner_admin
    if owner is None:
        return {"id": None, "name": ""}
    owner_user = owner.user
    return {"id": owner_user.pk, "name": owner_user.nickname}


def _quota_evidence(
    *,
    action_key: str,
    target_id,
    payload: dict[str, Any],
    safe_result: dict[str, Any],
    outcome: str,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "quota_type": "",
        "quota_before": None,
        "quota_requested_delta": None,
        "quota_delta": None,
        "quota_after": None,
        "ledger_entry_id": None,
        "reason": str(payload.get("reason", ""))[:500],
        "target_user": None,
    }
    if action_key not in QUOTA_ACTION_SIGNS:
        return evidence

    amount = payload.get("amount")
    if isinstance(amount, int):
        evidence["quota_requested_delta"] = QUOTA_ACTION_SIGNS[action_key] * amount

    from apps.quotas.models import QuotaAccount, QuotaLedgerEntry

    ledger_id = safe_result.get("ledger_entry_id")
    if ledger_id:
        entry = (
            QuotaLedgerEntry.objects.select_related("user", "user__tenant")
            .filter(pk=ledger_id)
            .first()
        )
        if entry is not None:
            evidence.update(
                {
                    "quota_type": entry.quota_type,
                    "quota_before": entry.available_before,
                    "quota_delta": entry.available_delta,
                    "quota_after": entry.available_after,
                    "ledger_entry_id": entry.pk,
                    "reason": entry.safe_reason[:500],
                    "target_user": entry.user,
                }
            )
            return evidence

    account = (
        QuotaAccount.objects.select_related("user", "user__tenant").filter(pk=target_id).first()
    )
    if account is not None:
        evidence["quota_type"] = account.quota_type
        evidence["target_user"] = account.user
        if outcome == SensitiveAuditLog.Outcome.FAILURE:
            evidence["quota_before"] = account.available
            evidence["quota_after"] = account.available
    return evidence


def record_sensitive_risk_action(
    *,
    request,
    action_key: str,
    target_id,
    outcome: str,
    actor: User | None,
    subject: User | None = None,
    payload: dict[str, Any] | None = None,
    safe_before: dict[str, Any] | None = None,
    safe_after: dict[str, Any] | None = None,
    safe_result: dict[str, Any] | None = None,
    failure_reason: str = "",
) -> SensitiveAuditLog | None:
    if not is_sensitive_action(action_key):
        return None

    request_id = validate_request_id(getattr(request, "request_id", ""))
    if request_id is None:
        raise ValueError("敏感审计日志必须包含规范 request_id。")

    payload = payload or {}
    safe_before = validate_safe_json(safe_before or {})
    safe_after = validate_safe_json(safe_after or {})
    safe_result = validate_safe_json(safe_result or {})
    actor_snapshot = _user_snapshot(actor)
    evidence = _quota_evidence(
        action_key=action_key,
        target_id=target_id,
        payload=payload,
        safe_result=safe_result,
        outcome=outcome,
    )
    target_user = evidence["target_user"] or subject
    target_snapshot = _user_snapshot(target_user)
    owner_snapshot = _owner_snapshot(target_user)
    reason = evidence["reason"] or str(
        payload.get("reason")
        or payload.get("opening_note")
        or payload.get("unavailable_reason")
        or ""
    )[:500]
    operation_ip = client_ip_address(request) or None

    # 管理员会话在 security.validate_admin_session() 中绑定登录时的 IP 指纹；
    # 能执行到敏感动作时，当前请求 IP 就是该管理会话的登录 IP。
    log = SensitiveAuditLog.objects.create(
        action_key=action_key,
        outcome=outcome,
        actor_user_id_snapshot=actor_snapshot["id"],
        actor_name_snapshot=actor_snapshot["name"],
        actor_role_snapshot=_actor_role(actor),
        actor_tenant_id_snapshot=actor_snapshot["tenant_id"],
        actor_tenant_name_snapshot=actor_snapshot["tenant_name"],
        target_user_id_snapshot=target_snapshot["id"],
        target_name_snapshot=target_snapshot["name"],
        target_owner_user_id_snapshot=owner_snapshot["id"],
        target_owner_name_snapshot=owner_snapshot["name"],
        target_tenant_id_snapshot=target_snapshot["tenant_id"],
        target_tenant_name_snapshot=target_snapshot["tenant_name"],
        quota_type=evidence["quota_type"],
        quota_before=evidence["quota_before"],
        quota_requested_delta=evidence["quota_requested_delta"],
        quota_delta=evidence["quota_delta"],
        quota_after=evidence["quota_after"],
        ledger_entry_id=evidence["ledger_entry_id"],
        request_id=request_id,
        operation_ip=operation_ip,
        login_ip_snapshot=operation_ip,
        user_agent=request_user_agent(request),
        safe_reason=reason,
        failure_reason=failure_reason[:128],
        details={
            "target_id": str(target_id),
            "safe_before": safe_before,
            "safe_after": safe_after,
        },
    )
    request._sensitive_audit_recorded = True
    return log


def sensitive_audit_was_recorded(request) -> bool:
    return bool(getattr(request, "_sensitive_audit_recorded", False))


def purge_expired_sensitive_audit_logs(
    *,
    now=None,
    batch_size: int = DEFAULT_PURGE_BATCH_SIZE,
    max_batches: int = DEFAULT_PURGE_MAX_BATCHES,
) -> int:
    if not 1 <= batch_size <= 10_000:
        raise ValueError("审计清理批次必须在 1 到 10000 之间。")
    if not 1 <= max_batches <= 10_000:
        raise ValueError("审计清理批次数必须在 1 到 10000 之间。")

    cutoff = (now or timezone.now()) - timedelta(days=RETENTION_DAYS)
    total = 0
    for _ in range(max_batches):
        ids = list(
            SensitiveAuditLog.objects.filter(created_at__lt=cutoff)
            .order_by("created_at", "id")
            .values_list("id", flat=True)[:batch_size]
        )
        if not ids:
            break
        queryset = SensitiveAuditLog.objects.filter(pk__in=ids)
        deleted, _ = models.QuerySet.delete(queryset)
        total += deleted
    return total
