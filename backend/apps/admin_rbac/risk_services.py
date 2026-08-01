import hashlib
import json
import re
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.core.redaction import is_sensitive_field, normalize_field_name
from apps.users.models import User

from .audit_services import record_audit_event
from .models import AdminProfile, ApprovalRequest, RiskAction, RiskPolicy, SuperuserSecurityPolicy
from .permissions import resolve_admin_context
from .risk_catalog import MODE_STRENGTH, PASSWORD, TWO_PERSON
from .risk_handlers import HandlerContext, handler_spec
from .security_services import _reauth

MAX_APPROVAL_PAYLOAD_BYTES = 16_384
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
    code = "APPROVAL_EXECUTION_FAILED"


class RiskConfirmationRequired(RiskError):
    code = "RISK_CONFIRMATION_REQUIRED"


class RiskPolicyVersionConflict(RiskError):
    code = "RISK_POLICY_VERSION_CONFLICT"


class RiskModeNotSupported(RiskError):
    code = "RISK_SECURITY_MODE_NOT_SUPPORTED"


class RiskModeBelowMinimum(RiskError):
    code = "RISK_SECURITY_MODE_BELOW_MINIMUM"


class ApprovalStateConflict(RiskError):
    code = "APPROVAL_STATE_CONFLICT"


class ApprovalSelfNotAllowed(RiskError):
    code = "APPROVAL_SELF_NOT_ALLOWED"


class ApprovalApproverUnavailable(RiskError):
    code = "APPROVAL_APPROVER_UNAVAILABLE"


class ApprovalExpired(RiskError):
    code = "APPROVAL_EXPIRED"


class ApprovalStale(RiskError):
    code = "APPROVAL_STALE"


class ApprovalPayloadInvalid(RiskError):
    code = "APPROVAL_PAYLOAD_INVALID"


@dataclass(frozen=True)
class RiskResult:
    approval_required: bool
    data: dict[str, Any]
    approval: ApprovalRequest | None = None
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
                raise ApprovalPayloadInvalid
            output[str(key)] = _json_value(item)
        return output
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        if isinstance(value, str):
            lowered = value.casefold()
            if any(marker in lowered for marker in FORBIDDEN_TEXT_MARKERS):
                raise ApprovalPayloadInvalid
            if HTML_TAG_PATTERN.search(value):
                raise ApprovalPayloadInvalid
            if any(ord(character) < 32 for character in value):
                raise ApprovalPayloadInvalid
        return value
    raise ApprovalPayloadInvalid


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
    if len(encoded) > MAX_APPROVAL_PAYLOAD_BYTES:
        raise ApprovalPayloadInvalid
    return safe_payload, hashlib.sha256(encoded).hexdigest()


def _context_with_permission(user, permission_key, *, request_permission=False):
    context = resolve_admin_context(user)
    if context is None or permission_key not in context.permission_keys:
        raise PermissionDenied
    if request_permission and "approvals.request" not in context.permission_keys:
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


def _ensure_other_approver(requester):
    candidates = User.objects.filter(
        is_superuser=True,
        is_staff=True,
        is_active=True,
        account_status__in=User.ACTIVE_ACCOUNT_STATUSES,
    ).exclude(pk=requester.pk)
    if not any(_valid_superuser(candidate) for candidate in candidates):
        raise ApprovalApproverUnavailable


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


def _mark_stale(approval, request, code="APPROVAL_STALE"):
    approval.status = ApprovalRequest.Status.STALE
    approval.stable_error_code = code
    approval.save(update_fields=["status", "stable_error_code", "updated_at"])
    record_audit_event(
        request=request,
        category="approval",
        action_key=approval.action_key,
        outcome="stale",
        actor=request.user,
        requester=approval.requester,
        approver=request.user if request.user.is_superuser else None,
        target_type=approval.target_type,
        target_id=approval.target_id,
        approval_request=approval,
        safe_after={"status": "stale"},
        stable_error_code=code,
    )


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
    if spec.superuser_only and not request.user.is_superuser:
        raise PermissionDenied
    actual_version = spec.target_version(request.user, context, target_id, True)
    if actual_version != target_version:
        raise ApprovalStale
    payload = _validated_payload(spec, raw_payload)
    safe_payload, digest = canonical_payload(
        action_key, policy.action.target_type, target_id, target_version, payload
    )
    mode = policy.current_mode
    if mode not in policy.action.supported_modes:
        raise RiskModeNotSupported
    definition_minimum = policy.action.minimum_mode
    if MODE_STRENGTH.get(mode, 0) < MODE_STRENGTH.get(definition_minimum, 99):
        raise RiskModeBelowMinimum
    if mode == TWO_PERSON:
        _context_with_permission(request.user, spec.permission_key, request_permission=True)
        _ensure_other_approver(request.user)
        expires_at = timezone.now() + timedelta(
            seconds=getattr(settings, "RISK_APPROVAL_TTL_SECONDS", 86_400)
        )
        try:
            with transaction.atomic():
                approval = ApprovalRequest.objects.create(
                    action=policy.action,
                    action_key=action_key,
                    policy_version=policy.version,
                    requester=request.user,
                    target_type=policy.action.target_type,
                    target_id=target_id,
                    target_version=target_version,
                    sanitized_payload=safe_payload,
                    payload_digest=digest,
                    safe_summary=f"{policy.action.name}（目标记录）",
                    expires_at=expires_at,
                    request_id=request.request_id,
                )
        except IntegrityError:
            approval = ApprovalRequest.objects.get(
                requester=request.user,
                action=policy.action,
                target_type=policy.action.target_type,
                target_id=target_id,
                payload_digest=digest,
                status=ApprovalRequest.Status.PENDING,
            )
        record_audit_event(
            request=request,
            category="approval",
            action_key=action_key,
            outcome="requested",
            actor=request.user,
            requester=request.user,
            target_type=policy.action.target_type,
            target_id=target_id,
            approval_request=approval,
            safe_after={"status": approval.status, "policy_version": policy.version},
        )
        return RiskResult(
            True,
            {
                "approval_required": True,
                "approval_id": str(approval.pk),
                "status": approval.status,
                "expires_at": approval.expires_at,
            },
            approval,
        )
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
        return RiskResult(False, {}, error=exc)
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
    return RiskResult(False, result.safe_result)


def perform_risk_action(**kwargs):
    result = _perform_risk_action_transactional(**kwargs)
    if result.error is not None:
        raise result.error
    return result


def _expire_locked_approval(*, approval, request, now=None):
    now = now or timezone.now()
    if approval.status != ApprovalRequest.Status.PENDING or approval.expires_at > now:
        return False
    approval.status = ApprovalRequest.Status.EXPIRED
    approval.save(update_fields=["status", "updated_at"])
    record_audit_event(
        request=request,
        category="approval",
        action_key=approval.action_key,
        outcome="expired",
        actor=request.user,
        requester=approval.requester,
        target_type=approval.target_type,
        target_id=approval.target_id,
        approval_request=approval,
        safe_after={"status": "expired"},
    )
    return True


@transaction.atomic
def expire_pending_approvals(*, request):
    now = timezone.now()
    approvals = list(
        ApprovalRequest.objects.select_for_update()
        .select_related("requester", "action")
        .filter(status=ApprovalRequest.Status.PENDING, expires_at__lte=now)
    )
    return sum(
        _expire_locked_approval(approval=approval, request=request, now=now)
        for approval in approvals
    )


@transaction.atomic
def get_approval_for_user(*, request, approval_id, permission_key="approvals.view"):
    approval = (
        ApprovalRequest.objects.select_for_update()
        .select_related("requester", "action")
        .filter(pk=approval_id)
        .first()
    )
    if approval is None:
        raise NotFound
    _context_with_permission(request.user, permission_key)
    if not request.user.is_superuser and approval.requester_id != request.user.pk:
        raise NotFound
    _expire_locked_approval(approval=approval, request=request)
    return approval


@transaction.atomic
def approve_request(*, request, approval_id, current_password):
    approval = get_approval_for_user(
        request=request, approval_id=approval_id, permission_key="approvals.approve"
    )
    if approval.status == ApprovalRequest.Status.EXPIRED:
        return approval
    if approval.status != ApprovalRequest.Status.PENDING:
        raise ApprovalStateConflict
    if approval.requester_id == request.user.pk:
        raise ApprovalSelfNotAllowed
    if not _valid_superuser(request.user):
        raise PermissionDenied
    _reauth(request.user, current_password, request)
    policy = _policy(approval.action_key, lock=True)
    spec = handler_spec(approval.action_key)
    if policy.version != approval.policy_version or policy.current_mode != TWO_PERSON:
        _mark_stale(approval, request)
        return approval
    requester = User.objects.select_for_update().get(pk=approval.requester_id)
    try:
        requester_context = _context_with_permission(
            requester, spec.permission_key, request_permission=True
        )
        if spec.superuser_only and not requester.is_superuser:
            raise PermissionDenied
        actual_version = spec.target_version(requester, requester_context, approval.target_id, True)
    except (PermissionDenied, NotFound):
        _mark_stale(approval, request)
        return approval
    safe_payload, digest = canonical_payload(
        approval.action_key,
        approval.target_type,
        approval.target_id,
        approval.target_version,
        approval.sanitized_payload,
    )
    if digest != approval.payload_digest or actual_version != approval.target_version:
        _mark_stale(approval, request)
        return approval
    approved_at = timezone.now()
    try:
        with transaction.atomic():
            result = spec.execute(
                HandlerContext(
                    requester=requester,
                    request=request,
                    target_id=approval.target_id,
                    target_version=approval.target_version,
                    payload=safe_payload,
                )
            )
    except Exception as exc:
        stable_code = getattr(exc, "code", "APPROVAL_EXECUTION_FAILED")
        approval.status = ApprovalRequest.Status.EXECUTION_FAILED
        approval.approved_by = request.user
        approval.approved_at = approved_at
        approval.executed_at = timezone.now()
        approval.stable_error_code = stable_code
        approval.save(
            update_fields=[
                "status",
                "approved_by",
                "approved_at",
                "executed_at",
                "stable_error_code",
                "updated_at",
            ]
        )
        record_audit_event(
            request=request,
            category="approval",
            action_key=approval.action_key,
            outcome="execution_failed",
            actor=request.user,
            requester=requester,
            approver=request.user,
            target_type=approval.target_type,
            target_id=approval.target_id,
            approval_request=approval,
            safe_after={"status": "execution_failed"},
            stable_error_code=stable_code,
        )
        return approval
    approval.status = ApprovalRequest.Status.EXECUTED
    approval.approved_by = request.user
    approval.approved_at = approved_at
    approval.executed_at = timezone.now()
    approval.execution_result = result.safe_result
    approval.save(
        update_fields=[
            "status",
            "approved_by",
            "approved_at",
            "executed_at",
            "execution_result",
            "updated_at",
        ]
    )
    record_audit_event(
        request=request,
        category="approval",
        action_key=approval.action_key,
        outcome="executed",
        actor=request.user,
        subject=result.subject,
        requester=requester,
        approver=request.user,
        target_type=approval.target_type,
        target_id=approval.target_id,
        approval_request=approval,
        safe_before=result.safe_before,
        safe_after=result.safe_after,
    )
    return approval


@transaction.atomic
def reject_request(*, request, approval_id, reason):
    approval = get_approval_for_user(
        request=request, approval_id=approval_id, permission_key="approvals.reject"
    )
    if approval.status == ApprovalRequest.Status.EXPIRED:
        return approval
    if approval.status != ApprovalRequest.Status.PENDING:
        raise ApprovalStateConflict
    if approval.requester_id == request.user.pk:
        raise ApprovalSelfNotAllowed
    if not _valid_superuser(request.user):
        raise PermissionDenied
    approval.status = ApprovalRequest.Status.REJECTED
    approval.rejected_by = request.user
    approval.rejected_at = timezone.now()
    approval.rejection_reason = reason
    approval.save(
        update_fields=["status", "rejected_by", "rejected_at", "rejection_reason", "updated_at"]
    )
    record_audit_event(
        request=request,
        category="approval",
        action_key=approval.action_key,
        outcome="rejected",
        actor=request.user,
        requester=approval.requester,
        approver=request.user,
        target_type=approval.target_type,
        target_id=approval.target_id,
        approval_request=approval,
        safe_after={"status": "rejected", "reason_provided": True},
    )
    return approval


@transaction.atomic
def _cancel_request_transactional(*, request, approval_id):
    approval = get_approval_for_user(
        request=request, approval_id=approval_id, permission_key="approvals.cancel"
    )
    if approval.status == ApprovalRequest.Status.EXPIRED:
        return approval
    if (
        approval.status != ApprovalRequest.Status.PENDING
        or approval.requester_id != request.user.pk
    ):
        raise ApprovalStateConflict
    approval.status = ApprovalRequest.Status.CANCELLED
    approval.cancelled_at = timezone.now()
    approval.save(update_fields=["status", "cancelled_at", "updated_at"])
    record_audit_event(
        request=request,
        category="approval",
        action_key=approval.action_key,
        outcome="cancelled",
        actor=request.user,
        requester=request.user,
        target_type=approval.target_type,
        target_id=approval.target_id,
        approval_request=approval,
        safe_after={"status": "cancelled"},
    )
    return approval


def cancel_request(*, request, approval_id):
    approval = _cancel_request_transactional(request=request, approval_id=approval_id)
    if approval.status == ApprovalRequest.Status.EXPIRED:
        raise ApprovalExpired
    return approval


@transaction.atomic
def update_risk_policy(
    *, request, action_key, current_mode, expected_version, current_password, confirmed
):
    if not request.user.is_superuser or not _valid_superuser(request.user):
        raise PermissionDenied
    _context_with_permission(request.user, "risk_policy.update")
    if confirmed is not True:
        raise RiskConfirmationRequired
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
