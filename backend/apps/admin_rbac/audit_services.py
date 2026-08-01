import json
from typing import Any

from apps.core.redaction import REDACTED, is_sensitive_field
from apps.core.request_ids import validate_request_id
from apps.users.services import client_ip_address

from .models import AuditEvent
from .security import admin_ip_fingerprint, admin_user_agent_digest

MAX_AUDIT_JSON_BYTES = 16_384


class UnsafeAuditData(ValueError):
    pass


def _validate_safe_value(value: Any, *, path: str = "root") -> Any:
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if is_sensitive_field(key_text):
                raise UnsafeAuditData(f"审计字段不允许包含敏感键：{path}.{key_text}")
            safe[key_text] = _validate_safe_value(item, path=f"{path}.{key_text}")
        return safe
    if isinstance(value, (list, tuple)):
        return [_validate_safe_value(item, path=f"{path}[]") for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, str) and value == REDACTED:
            raise UnsafeAuditData("审计数据不能以脱敏占位符替代被禁止的原值。")
        return value
    raise UnsafeAuditData(f"审计字段不可序列化：{path}")


def validate_safe_json(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise UnsafeAuditData("审计摘要必须是对象。")
    safe = _validate_safe_value(value)
    encoded = json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    if len(encoded) > MAX_AUDIT_JSON_BYTES:
        raise UnsafeAuditData("审计摘要过大。")
    return safe


def record_audit_event(
    *,
    request,
    category: str,
    action_key: str,
    outcome: str,
    actor=None,
    subject=None,
    requester=None,
    approver=None,
    target_type: str,
    target_id,
    approval_request=None,
    safe_before=None,
    safe_after=None,
    stable_error_code: str = "",
) -> AuditEvent:
    request_id = validate_request_id(getattr(request, "request_id", ""))
    if request_id is None:
        raise ValueError("审计事件必须包含规范 request_id。")
    before = validate_safe_json(safe_before or {})
    after = validate_safe_json(safe_after or {})
    return AuditEvent.objects.create(
        category=category,
        action_key=action_key,
        outcome=outcome,
        actor=actor,
        subject=subject,
        requester=requester,
        approver=approver,
        target_type=target_type,
        target_id=target_id,
        request_id=request_id,
        approval_request=approval_request,
        safe_before=before,
        safe_after=after,
        stable_error_code=stable_error_code,
        ip_fingerprint=admin_ip_fingerprint(client_ip_address(request)),
        user_agent_digest=admin_user_agent_digest(
            (request.META.get("HTTP_USER_AGENT", "") or "")[:512]
        ),
    )
