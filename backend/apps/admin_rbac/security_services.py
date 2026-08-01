from django.conf import settings
from django.db import transaction
from django.db.models import F

from apps.users.models import User
from apps.users.rate_limits import LoginRateLimiter, LoginRateLimitUnavailable
from apps.users.services import client_ip_address, rate_limit_keys
from apps.users.validators import validate_safe_plain_text

from .models import (
    AdminProfile,
    AdminRole,
    IpAllowlistStatus,
    RoleIpAllowlistEntry,
    SuperuserIpAllowlistEntry,
    SuperuserSecurityPolicy,
)
from .security import (
    AdminIpNotAllowed,
    AdminReauthFailed,
    AdminReauthRateLimited,
    AdminSecurityUnavailable,
    LockoutConfirmationRequired,
    SecurityPolicyVersionConflict,
    normalize_network,
    record_security_event,
)


def _reauth(actor: User, current_password: str, request) -> None:
    limiter = LoginRateLimiter(namespace="admin-reauth")
    limiter.window_seconds = settings.ADMIN_REAUTH_LIMIT_WINDOW_SECONDS
    limiter.lock_seconds = settings.ADMIN_REAUTH_LIMIT_WINDOW_SECONDS
    limiter.thresholds = {
        "combination": settings.ADMIN_REAUTH_LIMIT_FAILURES,
        "phone": settings.ADMIN_REAUTH_LIMIT_FAILURES,
        "ip": settings.ADMIN_REAUTH_LIMIT_FAILURES,
    }
    keys = rate_limit_keys(request, actor.phone)
    try:
        limiter.ensure_allowed(keys)
    except PermissionError as exc:
        raise AdminReauthRateLimited from exc
    except LoginRateLimitUnavailable as exc:
        raise AdminSecurityUnavailable from exc
    if not actor.check_password(current_password):
        try:
            limiter.register_failure(keys)
        except LoginRateLimitUnavailable as exc:
            raise AdminReauthFailed from exc
        raise AdminReauthFailed
    try:
        limiter.clear_successful_combination(keys)
    except LoginRateLimitUnavailable as exc:
        raise AdminReauthFailed from exc


def _superuser(actor_id) -> User:
    actor = User.objects.select_for_update().get(pk=actor_id)
    if not actor.is_superuser or not actor.is_active or not actor.is_staff:
        raise AdminReauthFailed
    profile = AdminProfile.objects.select_for_update().get(user=actor)
    if profile.admin_status != AdminProfile.Status.ACTIVE or profile.role_id is not None:
        raise AdminReauthFailed
    return actor


def _current_ip_would_be_allowed(request, entries) -> bool:
    import ipaddress

    candidate = ipaddress.ip_address(client_ip_address(request))
    return any(candidate in ipaddress.ip_network(item.network_cidr) for item in entries)


def _require_lockout_confirmation(request, enabled: bool, entries, confirmed: bool) -> None:
    if enabled and not _current_ip_would_be_allowed(request, entries) and not confirmed:
        raise LockoutConfirmationRequired


def _bump_role_security(role: AdminRole) -> None:
    role.security_version += 1
    role.save(update_fields=["security_version", "updated_at"])
    User.objects.filter(admin_profile__role=role).update(session_version=F("session_version") + 1)


@transaction.atomic
def update_role_security(
    *,
    actor_id,
    role_id,
    current_password,
    expected_security_version,
    request,
    require_sms_2fa=None,
    ip_allowlist_enabled=None,
    confirm_lockout=False,
):
    actor = _superuser(actor_id)
    _reauth(actor, current_password, request)
    role = AdminRole.objects.select_for_update().get(pk=role_id)
    if role.security_version != expected_security_version:
        raise SecurityPolicyVersionConflict
    enabled = role.ip_allowlist_enabled if ip_allowlist_enabled is None else ip_allowlist_enabled
    entries = list(role.ip_allowlist_entries.filter(status=IpAllowlistStatus.ACTIVE))
    if enabled and not entries:
        raise AdminIpNotAllowed
    _require_lockout_confirmation(request, enabled, entries, confirm_lockout)
    changed = False
    if require_sms_2fa is not None and role.require_sms_2fa != require_sms_2fa:
        role.require_sms_2fa = require_sms_2fa
        changed = True
    if ip_allowlist_enabled is not None and role.ip_allowlist_enabled != ip_allowlist_enabled:
        role.ip_allowlist_enabled = ip_allowlist_enabled
        changed = True
    if changed:
        role.security_version += 1
        role.save(
            update_fields=[
                "require_sms_2fa",
                "ip_allowlist_enabled",
                "security_version",
                "updated_at",
            ]
        )
        User.objects.filter(admin_profile__role=role).update(
            session_version=F("session_version") + 1
        )
        record_security_event(request=request, event_type="security_policy_changed", actor=actor)
    return role


@transaction.atomic
def create_role_ip_entry(
    *,
    actor_id,
    role_id,
    network_cidr,
    label,
    current_password,
    expected_security_version,
    confirm_lockout,
    request,
):
    actor = _superuser(actor_id)
    _reauth(actor, current_password, request)
    role = AdminRole.objects.select_for_update().get(pk=role_id)
    if role.security_version != expected_security_version:
        raise SecurityPolicyVersionConflict
    cidr, version = normalize_network(network_cidr)
    label = validate_safe_plain_text(
        label, field_label="白名单标签", max_length=100, required=False
    )
    entry = RoleIpAllowlistEntry.objects.filter(role=role, network_cidr=cidr).first()
    if entry:
        entry.label = label
        entry.status = IpAllowlistStatus.ACTIVE
        entry.save(update_fields=["label", "status", "updated_at"])
    else:
        entry = RoleIpAllowlistEntry.objects.create(
            role=role, network_cidr=cidr, ip_version=version, label=label
        )
    entries = list(role.ip_allowlist_entries.filter(status=IpAllowlistStatus.ACTIVE))
    _require_lockout_confirmation(request, role.ip_allowlist_enabled, entries, confirm_lockout)
    _bump_role_security(role)
    record_security_event(request=request, event_type="allowlist_changed", actor=actor)
    return entry, role


@transaction.atomic
def update_role_ip_entry(
    *,
    actor_id,
    role_id,
    entry_id,
    status,
    current_password,
    expected_security_version,
    confirm_lockout,
    request,
    label=None,
):
    actor = _superuser(actor_id)
    _reauth(actor, current_password, request)
    role = AdminRole.objects.select_for_update().get(pk=role_id)
    if role.security_version != expected_security_version:
        raise SecurityPolicyVersionConflict
    entry = RoleIpAllowlistEntry.objects.select_for_update().get(pk=entry_id, role=role)
    entry.status = status
    if label is not None:
        entry.label = validate_safe_plain_text(
            label, field_label="白名单标签", max_length=100, required=False
        )
    entry.save(update_fields=["status", "label", "updated_at"])
    entries = list(role.ip_allowlist_entries.filter(status=IpAllowlistStatus.ACTIVE))
    if role.ip_allowlist_enabled and not entries:
        raise AdminIpNotAllowed
    _require_lockout_confirmation(request, role.ip_allowlist_enabled, entries, confirm_lockout)
    _bump_role_security(role)
    record_security_event(request=request, event_type="allowlist_changed", actor=actor)
    return entry, role


@transaction.atomic
def update_superuser_security(
    *,
    actor_id,
    current_password,
    expected_security_version,
    request,
    ip_allowlist_enabled=None,
    confirm_lockout=False,
):
    actor = _superuser(actor_id)
    _reauth(actor, current_password, request)
    policy = SuperuserSecurityPolicy.objects.select_for_update().get(user=actor)
    if policy.security_version != expected_security_version:
        raise SecurityPolicyVersionConflict
    enabled = policy.ip_allowlist_enabled if ip_allowlist_enabled is None else ip_allowlist_enabled
    entries = list(policy.ip_allowlist_entries.filter(status=IpAllowlistStatus.ACTIVE))
    if enabled and not entries:
        raise AdminIpNotAllowed
    _require_lockout_confirmation(request, enabled, entries, confirm_lockout)
    if ip_allowlist_enabled is not None and policy.ip_allowlist_enabled != ip_allowlist_enabled:
        policy.ip_allowlist_enabled = ip_allowlist_enabled
        policy.security_version += 1
        policy.save(update_fields=["ip_allowlist_enabled", "security_version", "updated_at"])
        User.objects.filter(pk=actor.pk).update(session_version=F("session_version") + 1)
        record_security_event(
            request=request, event_type="security_policy_changed", actor=actor, subject=actor
        )
    return policy


@transaction.atomic
def create_superuser_ip_entry(
    *,
    actor_id,
    network_cidr,
    label,
    current_password,
    expected_security_version,
    confirm_lockout,
    request,
):
    actor = _superuser(actor_id)
    _reauth(actor, current_password, request)
    policy = SuperuserSecurityPolicy.objects.select_for_update().get(user=actor)
    if policy.security_version != expected_security_version:
        raise SecurityPolicyVersionConflict
    cidr, version = normalize_network(network_cidr)
    label = validate_safe_plain_text(
        label, field_label="白名单标签", max_length=100, required=False
    )
    entry = SuperuserIpAllowlistEntry.objects.filter(policy=policy, network_cidr=cidr).first()
    if entry:
        entry.label = label
        entry.status = IpAllowlistStatus.ACTIVE
        entry.save(update_fields=["label", "status", "updated_at"])
    else:
        entry = SuperuserIpAllowlistEntry.objects.create(
            policy=policy, network_cidr=cidr, ip_version=version, label=label
        )
    entries = list(policy.ip_allowlist_entries.filter(status=IpAllowlistStatus.ACTIVE))
    _require_lockout_confirmation(request, policy.ip_allowlist_enabled, entries, confirm_lockout)
    policy.security_version += 1
    policy.save(update_fields=["security_version", "updated_at"])
    User.objects.filter(pk=actor.pk).update(session_version=F("session_version") + 1)
    record_security_event(
        request=request, event_type="allowlist_changed", actor=actor, subject=actor
    )
    return entry, policy


@transaction.atomic
def update_superuser_ip_entry(
    *,
    actor_id,
    entry_id,
    status,
    current_password,
    expected_security_version,
    confirm_lockout,
    request,
    label=None,
):
    actor = _superuser(actor_id)
    _reauth(actor, current_password, request)
    policy = SuperuserSecurityPolicy.objects.select_for_update().get(user=actor)
    if policy.security_version != expected_security_version:
        raise SecurityPolicyVersionConflict
    entry = SuperuserIpAllowlistEntry.objects.select_for_update().get(pk=entry_id, policy=policy)
    entry.status = status
    if label is not None:
        entry.label = validate_safe_plain_text(
            label, field_label="白名单标签", max_length=100, required=False
        )
    entry.save(update_fields=["status", "label", "updated_at"])
    entries = list(policy.ip_allowlist_entries.filter(status=IpAllowlistStatus.ACTIVE))
    if policy.ip_allowlist_enabled and not entries:
        raise AdminIpNotAllowed
    _require_lockout_confirmation(request, policy.ip_allowlist_enabled, entries, confirm_lockout)
    policy.security_version += 1
    policy.save(update_fields=["security_version", "updated_at"])
    User.objects.filter(pk=actor.pk).update(session_version=F("session_version") + 1)
    record_security_event(
        request=request, event_type="allowlist_changed", actor=actor, subject=actor
    )
    return entry, policy
