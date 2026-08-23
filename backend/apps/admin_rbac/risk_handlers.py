from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from rest_framework.exceptions import NotFound, PermissionDenied

from apps.users.models import User
from apps.users.status_services import change_account_status, review_user

from .models import (
    AdminProfile,
    AdminRole,
    CustomerAssignment,
    SuperuserSecurityPolicy,
)
from .permissions import AdminContext, resolve_admin_context
from .risk_serializers import (
    AdminRoleChangePayloadSerializer,
    CustomerAssignmentPayloadSerializer,
    EmptyPayloadSerializer,
    IpAllowlistPayloadSerializer,
    ReasonPayloadSerializer,
    RejectUserPayloadSerializer,
    RolePermissionsPayloadSerializer,
    RoleSecurityPayloadSerializer,
)
from .scopes import scoped_customer_or_404
from .security import force_logout_admin
from .security_services import (
    create_role_ip_entry,
    create_superuser_ip_entry,
    update_role_ip_entry,
    update_role_security,
    update_superuser_ip_entry,
    update_superuser_security,
)
from .services import assign_customer, change_admin_status, disable_role, update_admin, update_role


@dataclass(frozen=True)
class HandlerResult:
    safe_before: dict[str, Any]
    safe_after: dict[str, Any]
    safe_result: dict[str, Any]
    subject: User | None = None


@dataclass(frozen=True)
class HandlerContext:
    requester: User
    request: Any
    target_id: Any
    target_version: int
    payload: dict[str, Any]
    current_password: str = ""
    approval_request: Any = None


@dataclass(frozen=True)
class HandlerSpec:
    permission_key: str
    superuser_only: bool
    payload_serializer: type
    target_version: Callable[[User, AdminContext, Any, bool], int]
    execute: Callable[[HandlerContext], HandlerResult]


def _profile_version(user, context, target_id, lock):
    query = AdminProfile.objects.select_related("user")
    if lock:
        query = query.select_for_update()
    try:
        profile = query.get(pk=target_id)
    except AdminProfile.DoesNotExist as exc:
        raise NotFound from exc
    return profile.version


def _profile_session_version(user, context, target_id, lock):
    query = AdminProfile.objects.select_related("user")
    if lock:
        query = query.select_for_update()
    try:
        profile = query.get(pk=target_id)
    except AdminProfile.DoesNotExist as exc:
        raise NotFound from exc
    user_query = User.objects.all()
    if lock:
        user_query = user_query.select_for_update()
    return user_query.only("session_version").get(pk=profile.user_id).session_version


def _role_version(user, context, target_id, lock):
    query = AdminRole.objects.all()
    if lock:
        query = query.select_for_update()
    try:
        role = query.get(pk=target_id)
    except AdminRole.DoesNotExist as exc:
        raise NotFound from exc
    return role.version


def _role_security_version(user, context, target_id, lock):
    query = AdminRole.objects.all()
    if lock:
        query = query.select_for_update()
    try:
        return query.get(pk=target_id).security_version
    except AdminRole.DoesNotExist as exc:
        raise NotFound from exc


def _superuser_policy_version(user, context, target_id, lock):
    if str(user.pk) != str(target_id):
        raise NotFound
    query = SuperuserSecurityPolicy.objects.all()
    if lock:
        query = query.select_for_update()
    try:
        return query.get(user=user).security_version
    except SuperuserSecurityPolicy.DoesNotExist as exc:
        raise NotFound from exc


def _customer_assignment_version(user, context, target_id, lock):
    customer = scoped_customer_or_404(user, context, target_id)
    query = CustomerAssignment.objects.all()
    if lock:
        query = query.select_for_update()
    try:
        return query.get(customer=customer).version
    except CustomerAssignment.DoesNotExist as exc:
        raise NotFound from exc


def _user_status_version(user, context, target_id, lock):
    customer = scoped_customer_or_404(user, context, target_id)
    if lock:
        customer = User.objects.select_for_update().get(pk=customer.pk)
    return customer.status_version


def _profile_snapshot(profile):
    return {
        "admin_status": profile.admin_status,
        "role_id": str(profile.role_id) if profile.role_id else None,
        "version": profile.version,
    }


def _role_snapshot(role):
    return {
        "status": role.status,
        "version": role.version,
        "security_version": role.security_version,
    }


def handle_admin_disable(context):
    profile = AdminProfile.objects.select_related("user").get(pk=context.target_id)
    before = _profile_snapshot(profile)
    profile = change_admin_status(
        actor_id=context.requester.pk,
        profile_id=profile.pk,
        action="disable",
        expected_version=context.target_version,
        request_id=context.request.request_id,
    )
    return HandlerResult(
        before,
        _profile_snapshot(profile),
        {"admin_id": str(profile.pk), "status": profile.admin_status},
        profile.user,
    )


def handle_admin_lock(context):
    profile = AdminProfile.objects.select_related("user").get(pk=context.target_id)
    before = _profile_snapshot(profile)
    profile = change_admin_status(
        actor_id=context.requester.pk,
        profile_id=profile.pk,
        action="lock",
        expected_version=context.target_version,
        request_id=context.request.request_id,
    )
    return HandlerResult(
        before,
        _profile_snapshot(profile),
        {"admin_id": str(profile.pk), "status": profile.admin_status},
        profile.user,
    )


def handle_admin_role_change(context):
    profile = AdminProfile.objects.select_related("user").get(pk=context.target_id)
    before = _profile_snapshot(profile)
    profile = update_admin(
        actor_id=context.requester.pk,
        profile_id=profile.pk,
        expected_version=context.target_version,
        role_id=context.payload["role_id"],
        request_id=context.request.request_id,
    )
    return HandlerResult(
        before,
        _profile_snapshot(profile),
        {"admin_id": str(profile.pk), "version": profile.version},
        profile.user,
    )


def handle_admin_force_logout(context):
    profile = AdminProfile.objects.select_related("user").get(pk=context.target_id)
    before = {"session_version": profile.user.session_version}
    profile = force_logout_admin(
        actor=context.requester, profile_id=profile.pk, request=context.request
    )
    profile.user.refresh_from_db(fields=["session_version"])
    after = {"session_version": profile.user.session_version}
    return HandlerResult(
        before, after, {"logged_out": True, "admin_id": str(profile.pk)}, profile.user
    )


def handle_role_permissions(context):
    role = AdminRole.objects.get(pk=context.target_id)
    before = _role_snapshot(role)
    role = update_role(
        actor_id=context.requester.pk,
        role_id=role.pk,
        expected_version=context.target_version,
        name=None,
        description=None,
        data_scope=None,
        permission_keys=context.payload["permission_keys"],
        request_id=context.request.request_id,
    )
    return HandlerResult(
        before, _role_snapshot(role), {"role_id": str(role.pk), "version": role.version}
    )


def handle_role_disable(context):
    role = AdminRole.objects.get(pk=context.target_id)
    before = _role_snapshot(role)
    role = disable_role(
        actor_id=context.requester.pk,
        role_id=role.pk,
        expected_version=context.target_version,
        request_id=context.request.request_id,
    )
    return HandlerResult(
        before, _role_snapshot(role), {"role_id": str(role.pk), "status": role.status}
    )


def handle_role_security(context):
    role = AdminRole.objects.get(pk=context.target_id)
    before = _role_snapshot(role)
    role = update_role_security(
        actor_id=context.requester.pk,
        role_id=role.pk,
        current_password=context.current_password,
        expected_security_version=context.target_version,
        request=context.request,
        **context.payload,
    )
    return HandlerResult(
        before,
        _role_snapshot(role),
        {"role_id": str(role.pk), "security_version": role.security_version},
    )


def handle_role_ip_allowlist(context):
    role = AdminRole.objects.get(pk=context.target_id)
    before = _role_snapshot(role)
    payload = dict(context.payload)
    operation = payload.pop("operation")
    if operation == "create":
        entry, role = create_role_ip_entry(
            actor_id=context.requester.pk,
            role_id=role.pk,
            current_password=context.current_password,
            expected_security_version=context.target_version,
            request=context.request,
            **payload,
        )
    else:
        entry, role = update_role_ip_entry(
            actor_id=context.requester.pk,
            role_id=role.pk,
            current_password=context.current_password,
            expected_security_version=context.target_version,
            request=context.request,
            **payload,
        )
    return HandlerResult(
        before,
        _role_snapshot(role),
        {"entry_id": str(entry.pk), "security_version": role.security_version},
    )


def handle_superuser_ip_allowlist(context):
    policy = SuperuserSecurityPolicy.objects.get(user=context.requester)
    before = {
        "security_version": policy.security_version,
        "ip_allowlist_enabled": policy.ip_allowlist_enabled,
    }
    payload = dict(context.payload)
    operation = payload.pop("operation")
    if operation == "policy":
        policy = update_superuser_security(
            actor_id=context.requester.pk,
            current_password=context.current_password,
            expected_security_version=context.target_version,
            request=context.request,
            **payload,
        )
        after = {
            "security_version": policy.security_version,
            "ip_allowlist_enabled": policy.ip_allowlist_enabled,
        }
        return HandlerResult(before, after, after, context.requester)
    if operation == "create":
        entry, policy = create_superuser_ip_entry(
            actor_id=context.requester.pk,
            current_password=context.current_password,
            expected_security_version=context.target_version,
            request=context.request,
            **payload,
        )
    else:
        entry, policy = update_superuser_ip_entry(
            actor_id=context.requester.pk,
            current_password=context.current_password,
            expected_security_version=context.target_version,
            request=context.request,
            **payload,
        )
    after = {
        "security_version": policy.security_version,
        "ip_allowlist_enabled": policy.ip_allowlist_enabled,
    }
    return HandlerResult(
        before,
        after,
        {"entry_id": str(entry.pk), "security_version": policy.security_version},
        context.requester,
    )


def handle_customer_assignment(context):
    admin_context = resolve_admin_context(context.requester)
    if admin_context is None:
        raise PermissionDenied
    customer = scoped_customer_or_404(context.requester, admin_context, context.target_id)
    before = {"version": context.target_version}
    assignment = assign_customer(
        actor=context.requester,
        context=admin_context,
        customer=customer,
        expected_version=context.target_version,
        request_id=context.request.request_id,
        **context.payload,
    )
    after = {
        "version": assignment.version,
        "owner_admin_id": str(assignment.owner_admin_id) if assignment.owner_admin_id else None,
    }
    return HandlerResult(
        before,
        after,
        {"assignment_id": str(assignment.pk), "version": assignment.version},
        customer,
    )


def handle_user_freeze(context):
    user = User.objects.get(pk=context.target_id)
    before = {"account_status": user.account_status, "status_version": user.status_version}
    result = change_account_status(
        actor_id=context.requester.pk,
        user_id=user.pk,
        action="freeze",
        reason=context.payload.get("reason", ""),
        request_id=context.request.request_id,
    )
    after = {
        "account_status": result.user.account_status,
        "status_version": result.user.status_version,
    }
    return HandlerResult(before, after, {"user_id": str(user.pk), **after}, user)


def handle_user_review_reject(context):
    user = User.objects.get(pk=context.target_id)
    before = {"approval_status": user.approval_status, "status_version": user.status_version}
    result = review_user(
        actor_id=context.requester.pk,
        user_id=user.pk,
        decision="reject",
        reason=context.payload["reason"],
        request_id=context.request.request_id,
    )
    after = {
        "approval_status": result.user.approval_status,
        "status_version": result.user.status_version,
    }
    return HandlerResult(before, after, {"user_id": str(user.pk), **after}, user)


HANDLER_REGISTRY = {
    "admin.disable": handle_admin_disable,
    "admin.lock": handle_admin_lock,
    "admin.role.change": handle_admin_role_change,
    "admin.force_logout": handle_admin_force_logout,
    "role.permissions.replace": handle_role_permissions,
    "role.disable": handle_role_disable,
    "role.security.update": handle_role_security,
    "role.ip_allowlist.update": handle_role_ip_allowlist,
    "superuser.ip_allowlist.update": handle_superuser_ip_allowlist,
    "customer.assignment.change": handle_customer_assignment,
    "user.freeze": handle_user_freeze,
    "user.review.reject": handle_user_review_reject,
}


HANDLER_SPECS = {
    "admin.disable": HandlerSpec(
        "admins.disable", True, EmptyPayloadSerializer, _profile_version, handle_admin_disable
    ),
    "admin.lock": HandlerSpec(
        "admins.disable", True, EmptyPayloadSerializer, _profile_version, handle_admin_lock
    ),
    "admin.role.change": HandlerSpec(
        "admins.update",
        True,
        AdminRoleChangePayloadSerializer,
        _profile_version,
        handle_admin_role_change,
    ),
    "admin.force_logout": HandlerSpec(
        "admins.disable",
        True,
        EmptyPayloadSerializer,
        _profile_session_version,
        handle_admin_force_logout,
    ),
    "role.permissions.replace": HandlerSpec(
        "roles.update",
        True,
        RolePermissionsPayloadSerializer,
        _role_version,
        handle_role_permissions,
    ),
    "role.disable": HandlerSpec(
        "roles.disable", True, EmptyPayloadSerializer, _role_version, handle_role_disable
    ),
    "role.security.update": HandlerSpec(
        "roles.update",
        True,
        RoleSecurityPayloadSerializer,
        _role_security_version,
        handle_role_security,
    ),
    "role.ip_allowlist.update": HandlerSpec(
        "roles.update",
        True,
        IpAllowlistPayloadSerializer,
        _role_security_version,
        handle_role_ip_allowlist,
    ),
    "superuser.ip_allowlist.update": HandlerSpec(
        "admins.update",
        True,
        IpAllowlistPayloadSerializer,
        _superuser_policy_version,
        handle_superuser_ip_allowlist,
    ),
    "customer.assignment.change": HandlerSpec(
        "users.assign",
        True,
        CustomerAssignmentPayloadSerializer,
        _customer_assignment_version,
        handle_customer_assignment,
    ),
    "user.freeze": HandlerSpec(
        "users.freeze", False, ReasonPayloadSerializer, _user_status_version, handle_user_freeze
    ),
    "user.review.reject": HandlerSpec(
        "users.review",
        False,
        RejectUserPayloadSerializer,
        _user_status_version,
        handle_user_review_reject,
    ),
}
from apps.plans.risk_handlers import (  # noqa: E402
    PLAN_HANDLER_REGISTRY,
    PLAN_HANDLER_SPECS,
)

HANDLER_REGISTRY.update(PLAN_HANDLER_REGISTRY)
HANDLER_SPECS.update(PLAN_HANDLER_SPECS)
from apps.quotas.risk_handlers import (  # noqa: E402
    QUOTA_HANDLER_REGISTRY,
    QUOTA_HANDLER_SPECS,
)

HANDLER_REGISTRY.update(QUOTA_HANDLER_REGISTRY)
HANDLER_SPECS.update(QUOTA_HANDLER_SPECS)
from apps.subjects.risk_handlers import (  # noqa: E402
    SUBJECT_RISK_HANDLER_REGISTRY,
    SUBJECT_RISK_HANDLER_SPECS,
)

HANDLER_REGISTRY.update(SUBJECT_RISK_HANDLER_REGISTRY)
HANDLER_SPECS.update(SUBJECT_RISK_HANDLER_SPECS)


def handler_spec(action_key: str) -> HandlerSpec:
    try:
        return HANDLER_SPECS[action_key]
    except KeyError as exc:
        raise LookupError("未知高风险动作。") from exc
