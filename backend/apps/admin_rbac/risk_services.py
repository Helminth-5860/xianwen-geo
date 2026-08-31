import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import transaction
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.core.redaction import is_sensitive_field, normalize_field_name
from apps.users.models import User

from .audit_services import record_audit_event
from .models import AdminProfile, RiskAction, RiskPolicy, SuperuserSecurityPolicy
from .permissions import resolve_admin_context
from .risk_catalog import MODE_STRENGTH, PASSWORD, requires_sms_step_up
from .risk_handlers import HandlerContext, handler_spec
from .security import require_admin_step_up
from .security_services import _reauth
from .sensitive_audit_models import SensitiveAuditLog
from .sensitive_audit_services import record_sensitive_risk_action

MAX_RISK_PAYLOAD_BYTES = 16_384
FORBIDDEN_TEXT_MARKERS = (
    "http://",
    "https://",
    "file://",
    "javascript:",
    "select ",
    "insert ",
    "update ",
    "delete ",
    "drop ",
    "exec(",
    "eval(",
    "import ",
)
HTML_TAG_PATTERN = re.compile(r"<\s*/?\s*[a-zA-Z][^>]*>")
FORBIDDEN_PAYLOAD_KEYS = {
    "password",
    "current_password",
    "sms_code",
    "cookie",
    "cookies",
    "session",
    "session_id",
    "challenge",
    "challenge_id",
    "api_key",
    "secret",
    "private_key",
    "access_token",
    "refresh_token",
    "sql",
    "command",
    "url",
    "callback_url",
    "import_path",
    "callable",
}


class RiskError(Exception):
    code = "RISK_ACTION_EXECUTION_FAILED"


class RiskConfirmationRequired(RiskError):
    code = "RISK_CONFIRMATION_REQUIRED"


class RiskPolicyVersionConflict(RiskError):
    code = "RISK_POLICY_VERSION_CONFLICT"


class RiskModeNotSupported(RiskError):
    code = "RISK_SECURITY_MODE_NOT_SUPPORTED"


class RiskModeBelowMinimum(RiskError):
    code = "RISK_SECURITY_MODE_BELOW_MINIMUM"


class RiskTargetStale(RiskError):
    code = "RISK_TARGET_STALE"


class RiskPayloadInvalid(RiskError):
    code = "RISK_PAYLOAD_INVALID"


@dataclass(frozen=True)
class RiskResult:
    data: dict[str, Any]
    error: Exception | None = None


def _json_value(value):
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        output = {}
        for key, item in value.items():
            normalized_key = normalize_field_name(key)
            if is_sensitive_field(key) or normalized_key in FORBIDDEN_PAYLOAD_KEYS:
                raise RiskPayloadInvalid
            output[str(key)] = _json_value(item)
        return output
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        if isinstance(value, str):
            lowered = value.casefold()
            if any(marker in lowered for marker in FORBIDDEN_TEXT_MARKERS):
                raise RiskPayloadInvalid
            if HTML_TAG_PATTERN.search(value):
                raise RiskPayloadInvalid
            if any(ord(character) < 32 for character in value):
                raise RiskPayloadInvalid
        return value
    raise RiskPayloadInvalid


def canonical_payload(action_key, target_type, target_id, target_version, payload):
    safe_payload = _json_value(payload)
    document = {
        "action_key": action_key,
        "target_type": target_type,
        "target_id": str(target_id),
        "target_version": target_version,
        "payload": safe_payload,
    }
    encoded = json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    if len(encoded) > MAX_RISK_PAYLOAD_BYTES:
        raise RiskPayloadInvalid
    return safe_payload, hashlib.sha256(encoded).hexdigest()


def _context_with_permission(user, permission_key):
    context = resolve_admin_context(user)
    if context is None or permission_key not in context.permission_keys:
        raise PermissionDenied
    return context


def _valid_superuser(user):
    if (
        not user.is_superuser
        or not user.is_staff
        or not user.is_active
        or user.account_status not in User.ACTIVE_ACCOUNT_STATUSES
    ):
        return False
    try:
        profile = user.admin_profile
        policy = user.superuser_security_policy
    except (AdminProfile.DoesNotExist, SuperuserSecurityPolicy.DoesNotExist):
        return False
    if profile.admin_status != AdminProfile.Status.ACTIVE or profile.role_id is not None:
        return False
    if (
        policy.ip_allowlist_enabled
        and not policy.ip_allowlist_entries.filter(status="active").exists()
    ):
        return False
    return True


def _validated_payload(spec, raw_payload):
    serializer = spec.payload_serializer(data=raw_payload)
    serializer.is_valid(raise_exception=True)
    safe = dict(serializer.validated_data)
    return _json_value(safe)


def _policy(action_key, *, lock):
    query = RiskPolicy.objects.select_related("action")
    if lock:
        query = query.select_for_update()
    try:
        policy = query.get(action_id=action_key, action__status=RiskAction.Status.ACTIVE)
    except RiskPolicy.DoesNotExist as exc:
        raise NotFound from exc
    return policy


@transaction.atomic
def _perform_risk_action_transactional(
    *,
    request,
    action_key,
    target_id,
    target_version,
    raw_payload,
    confirmed=False,
    current_password="",
):
    policy = _policy(action_key, lock=True)
    spec = handler_spec(action_key)
    context = _context_with_permission(request.user, spec.permission_key)
    if requires_sms_step_up(action_key):
        require_admin_step_up(request)
    if spec.superuser_only and not request.user.is_superuser:
        raise PermissionDenied
    actual_version = spec.target_version(request.user, context, target_id, True)
    if actual_version != target_version:
        raise RiskTargetStale
    payload = _validated_payload(spec, raw_payload)
    canonical_payload(action_key, policy.action.target_type, target_id, target_version, payload)
    mode = policy.current_mode
    if mode not in policy.action.supported_modes:
        raise RiskModeNotSupported
    definition_minimum = policy.action.minimum_mode
    if MODE_STRENGTH.get(mode, 0) < MODE_STRENGTH.get(definition_minimum, 99):
        raise RiskModeBelowMinimum
    if mode == PASSWORD:
        if not current_password:
            raise ValidationError({"current_password": ["密码模式必须提供当前密码。"]})
        _reauth(request.user, current_password, request)
    elif mode == "confirm" and confirmed is not True:
        raise RiskConfirmationRequired
    try:
        with transaction.atomic():
            result = spec.execute(
                HandlerContext(
                    requester=request.user,
                    request=request,
                    target_id=target_id,
                    target_version=target_version,
                    payload=payload,
                    current_password=current_password,
                )
            )
    except Exception as exc:
        stable_code = getattr(exc, "code", exc.__class__.__name__.upper())
        record_audit_event(
            request=request,
            category="high_risk_action",
            action_key=action_key,
            outcome="execution_failed",
            actor=request.user,
            requester=request.user,
            target_type=policy.action.target_type,
            target_id=target_id,
            safe_after={"executed": False},
            stable_error_code=stable_code[:64],
        )
        record_sensitive_risk_action(
            request=request,
            action_key=action_key,
            target_id=target_id,
            outcome=SensitiveAuditLog.Outcome.FAILURE,
            actor=request.user,
            payload=payload,
            safe_after={"executed": False},
            failure_reason=stable_code,
        )
        return RiskResult({}, error=exc)
    record_audit_event(
        request=request,
        category="high_risk_action",
        action_key=action_key,
        outcome="executed",
        actor=request.user,
        subject=result.subject,
        requester=request.user,
        target_type=policy.action.target_type,
        target_id=target_id,
        safe_before=result.safe_before,
        safe_after=result.safe_after,
    )
    record_sensitive_risk_action(
        request=request,
        action_key=action_key,
        target_id=target_id,
        outcome=SensitiveAuditLog.Outcome.SUCCESS,
        actor=request.user,
        subject=result.subject,
        payload=payload,
        safe_before=result.safe_before,
        safe_after=result.safe_after,
        safe_result=result.safe_result,
    )
    return RiskResult(result.safe_result)


def perform_risk_action(**kwargs):
    result = _perform_risk_action_transactional(**kwargs)
    if result.error is not None:
        raise result.error
    return result


@transaction.atomic
def update_risk_policy(
    *, request, action_key, current_mode, expected_version, current_password, confirmed
):
    if not request.user.is_superuser or not _valid_superuser(request.user):
        raise PermissionDenied
    _context_with_permission(request.user, "risk_policy.update")
    if confirmed is not True:
        raise RiskConfirmationRequired
    require_admin_step_up(request)
    _reauth(request.user, current_password, request)
    policy = _policy(action_key, lock=True)
    if policy.version != expected_version:
        raise RiskPolicyVersionConflict
    definition = policy.action
    if current_mode not in definition.supported_modes:
        raise RiskModeNotSupported
    if MODE_STRENGTH.get(current_mode, 0) < MODE_STRENGTH.get(definition.minimum_mode, 99):
        raise RiskModeBelowMinimum
    before = {"current_mode": policy.current_mode, "version": policy.version}
    if policy.current_mode != current_mode:
        policy.current_mode = current_mode
        policy.version += 1
        policy.updated_by = request.user
        policy.save(update_fields=["current_mode", "version", "updated_by", "updated_at"])
    record_audit_event(
        request=request,
        category="risk_policy",
        action_key="risk.policy.update",
        outcome="updated",
        actor=request.user,
        requester=request.user,
        target_type="risk_action",
        target_id=policy.pk,
        safe_before=before,
        safe_after={
            "action_key": action_key,
            "current_mode": policy.current_mode,
            "version": policy.version,
        },
    )
    return policy
