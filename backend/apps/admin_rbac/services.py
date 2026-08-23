from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied

from apps.users.models import Tenant, User
from apps.users.validators import validate_nickname, validate_safe_plain_text

from .catalog import CATALOG_BY_KEY
from .models import (
    AdminPermission,
    AdminProfile,
    AdminRbacEvent,
    AdminRole,
    AdminRolePermission,
    CustomerAssignment,
)


class DomainConflict(Exception):
    code = ""


class AdminStateConflict(DomainConflict):
    code = "ADMIN_STATE_CONFLICT"


class AdminVersionConflict(DomainConflict):
    code = "ADMIN_VERSION_CONFLICT"


class AdminHasAssignedCustomers(DomainConflict):
    code = "ADMIN_HAS_ASSIGNED_CUSTOMERS"


class LastSuperuserProtected(DomainConflict):
    code = "LAST_SUPERUSER_PROTECTED"


class RoleVersionConflict(DomainConflict):
    code = "ROLE_VERSION_CONFLICT"


class RoleInUse(DomainConflict):
    code = "ROLE_IN_USE"


class AssignmentVersionConflict(DomainConflict):
    code = "ASSIGNMENT_VERSION_CONFLICT"


@transaction.atomic
def set_permission_status(*, permission_key: str, status: str) -> AdminPermission:
    if status not in AdminPermission.Status.values:
        raise ValueError("无效的权限状态。")
    permission = AdminPermission.objects.select_for_update().get(key=permission_key)
    if permission.status == status:
        return permission

    previous_status = permission.status
    AdminPermission.objects.filter(pk=permission.pk).update(status=status)
    permission.status = status
    if (
        previous_status == AdminPermission.Status.ACTIVE
        and status == AdminPermission.Status.INACTIVE
    ):
        role_ids = list(
            AdminRolePermission.objects.filter(
                permission=permission,
                role__status=AdminRole.Status.ACTIVE,
            ).values_list("role_id", flat=True)
        )
        if role_ids:
            User.objects.filter(
                is_superuser=False,
                admin_profile__role_id__in=role_ids,
            ).update(session_version=F("session_version") + 1)
    return permission


def _event(*, actor, target, target_type, event_type, before, after, request_id):
    return AdminRbacEvent.objects.create(
        actor=actor,
        target_type=target_type,
        target_id=target.pk,
        event_type=event_type,
        safe_before=before,
        safe_after=after,
        request_id=request_id,
    )


def _locked_superuser(actor_id) -> tuple[User, AdminProfile]:
    actor = User.objects.select_for_update().get(pk=actor_id)
    if not actor.is_superuser or not actor.is_staff or not actor.is_active:
        raise PermissionDenied
    try:
        profile = AdminProfile.objects.select_for_update().get(user=actor)
    except AdminProfile.DoesNotExist as exc:
        raise PermissionDenied from exc
    if profile.admin_status != AdminProfile.Status.ACTIVE or profile.role_id is not None:
        raise PermissionDenied
    return actor, profile


def _active_role(role_id) -> AdminRole:
    try:
        role = AdminRole.objects.select_for_update().get(pk=role_id)
    except AdminRole.DoesNotExist as exc:
        raise NotFound from exc
    if role.status != AdminRole.Status.ACTIVE:
        raise RoleInUse
    return role


@transaction.atomic
def create_role(*, actor_id, name, description, data_scope, request_id):
    actor, _ = _locked_superuser(actor_id)
    role = AdminRole.objects.create(
        name=validate_safe_plain_text(name, field_label="角色名称", max_length=80, required=True),
        description=validate_safe_plain_text(
            description, field_label="角色说明", max_length=500, required=False
        ),
        data_scope=data_scope,
    )
    _event(
        actor=actor,
        target=role,
        target_type="role",
        event_type="role_created",
        before={},
        after={"status": role.status, "data_scope": role.data_scope, "version": role.version},
        request_id=request_id,
    )
    return role


@transaction.atomic
def update_role(
    *,
    actor_id,
    role_id,
    expected_version,
    name,
    description,
    data_scope,
    permission_keys,
    request_id,
):
    actor, _ = _locked_superuser(actor_id)
    role = AdminRole.objects.select_for_update().get(pk=role_id)
    if role.version != expected_version:
        raise RoleVersionConflict
    before = {"status": role.status, "data_scope": role.data_scope, "version": role.version}
    if name is not None:
        role.name = validate_safe_plain_text(
            name, field_label="角色名称", max_length=80, required=True
        )
    if description is not None:
        role.description = validate_safe_plain_text(
            description, field_label="角色说明", max_length=500, required=False
        )
    if data_scope is not None:
        role.data_scope = data_scope
    if permission_keys is not None:
        if any(key not in CATALOG_BY_KEY for key in permission_keys):
            raise PermissionDenied
        permissions = list(
            AdminPermission.objects.filter(
                key__in=permission_keys,
                status=AdminPermission.Status.ACTIVE,
                superuser_only=False,
            )
        )
        if len(permissions) != len(set(permission_keys)):
            raise PermissionDenied
        AdminRolePermission.objects.filter(role=role).delete()
        AdminRolePermission.objects.bulk_create(
            [AdminRolePermission(role=role, permission=item) for item in permissions]
        )
    role.version += 1
    role.save()
    User.objects.filter(admin_profile__role=role).update(session_version=F("session_version") + 1)
    _event(
        actor=actor,
        target=role,
        target_type="role",
        event_type="role_updated",
        before=before,
        after={"status": role.status, "data_scope": role.data_scope, "version": role.version},
        request_id=request_id,
    )
    return role


@transaction.atomic
def disable_role(*, actor_id, role_id, expected_version, request_id):
    actor, _ = _locked_superuser(actor_id)
    role = AdminRole.objects.select_for_update().get(pk=role_id)
    if role.version != expected_version:
        raise RoleVersionConflict
    if role.status != AdminRole.Status.ACTIVE:
        raise RoleVersionConflict
    if role.admin_profiles.exists():
        raise RoleInUse
    role.status = AdminRole.Status.INACTIVE
    role.version += 1
    role.save(update_fields=["status", "version", "updated_at"])
    _event(
        actor=actor,
        target=role,
        target_type="role",
        event_type="role_disabled",
        before={"status": "active", "version": expected_version},
        after={"status": role.status, "version": role.version},
        request_id=request_id,
    )
    return role


@transaction.atomic
def create_admin(*, actor_id, phone, nickname, password, role_id, request_id, tenant_id=None):
    actor, _ = _locked_superuser(actor_id)
    role = _active_role(role_id)
    tenant = (
        Tenant.objects.get(pk=tenant_id, status=Tenant.Status.ACTIVE)
        if tenant_id is not None
        else None
    )
    user = User.objects.create_user(
        phone=phone,
        password=password,
        nickname=validate_nickname(nickname),
        tenant=tenant,
        is_staff=True,
        is_superuser=False,
        approval_status=User.ApprovalStatus.APPROVED,
        approved_at=timezone.now(),
        approved_by=actor,
        account_status=User.AccountStatus.ACTIVE,
    )
    profile = AdminProfile.objects.create(user=user, role=role)
    _event(
        actor=actor,
        target=profile,
        target_type="admin",
        event_type="admin_created",
        before={},
        after={"admin_status": profile.admin_status, "role_id": str(role.id), "version": 1},
        request_id=request_id,
    )
    return profile


@transaction.atomic
def update_admin(
    *, actor_id, profile_id, expected_version, nickname=None, role_id=None, request_id
):
    actor, _ = _locked_superuser(actor_id)
    profile = AdminProfile.objects.select_for_update().select_related("user").get(pk=profile_id)
    if profile.version != expected_version:
        raise AdminVersionConflict
    if profile.user.is_superuser:
        raise PermissionDenied
    before = {"role_id": str(profile.role_id), "version": profile.version}
    if nickname is not None:
        profile.user.nickname = validate_nickname(nickname)
        profile.user.save(update_fields=["nickname", "updated_at"])
    if role_id is not None:
        profile.role = _active_role(role_id)
        profile.user.session_version += 1
        profile.user.save(update_fields=["session_version", "updated_at"])
    profile.version += 1
    profile.save(update_fields=["role", "version", "updated_at"])
    _event(
        actor=actor,
        target=profile,
        target_type="admin",
        event_type="admin_updated",
        before=before,
        after={"role_id": str(profile.role_id), "version": profile.version},
        request_id=request_id,
    )
    return profile


@transaction.atomic
def change_admin_status(*, actor_id, profile_id, action, expected_version, request_id):
    superusers = list(User.objects.select_for_update().filter(is_superuser=True).order_by("id"))
    profiles = list(
        AdminProfile.objects.select_for_update()
        .select_related("user")
        .filter(user_id__in=[user.id for user in superusers])
        .order_by("user_id")
    )
    actor = next((user for user in superusers if user.pk == actor_id), None)
    actor_profile = next((item for item in profiles if item.user_id == actor_id), None)
    if actor is None or actor_profile is None:
        raise PermissionDenied
    if (
        not actor.is_staff
        or not actor.is_active
        or actor_profile.admin_status != AdminProfile.Status.ACTIVE
        or actor_profile.role_id is not None
    ):
        raise LastSuperuserProtected
    profile = next((item for item in profiles if item.pk == profile_id), None)
    if profile is None:
        profile = AdminProfile.objects.select_for_update().select_related("user").get(pk=profile_id)
    if profile.version != expected_version:
        raise AdminVersionConflict
    transitions: dict[tuple[str, str], str] = {
        ("disable", AdminProfile.Status.ACTIVE): AdminProfile.Status.DISABLED,
        ("lock", AdminProfile.Status.ACTIVE): AdminProfile.Status.LOCKED,
        ("enable", AdminProfile.Status.DISABLED): AdminProfile.Status.ACTIVE,
        ("unlock", AdminProfile.Status.LOCKED): AdminProfile.Status.ACTIVE,
    }
    new_status = transitions.get((action, profile.admin_status))
    if new_status is None:
        raise AdminStateConflict
    if action == "disable" and profile.customer_assignments.exists():
        raise AdminHasAssignedCustomers
    if profile.user.is_superuser and new_status != AdminProfile.Status.ACTIVE:
        active_count = sum(
            item.admin_status == AdminProfile.Status.ACTIVE
            and item.user.is_staff
            and item.user.is_active
            for item in profiles
        )
        if active_count <= 1:
            raise LastSuperuserProtected
    before = {"admin_status": profile.admin_status, "version": profile.version}
    profile.admin_status = new_status
    profile.version += 1
    profile.user.is_staff = new_status == AdminProfile.Status.ACTIVE
    profile.user.session_version += 1
    profile.user.save(update_fields=["is_staff", "session_version", "updated_at"])
    profile.save(update_fields=["admin_status", "version", "updated_at"])
    _event(
        actor=actor,
        target=profile,
        target_type="admin",
        event_type=f"admin_{action}",
        before=before,
        after={"admin_status": profile.admin_status, "version": profile.version},
        request_id=request_id,
    )
    return profile


@transaction.atomic
def assign_customer(
    *, actor, context, customer, owner_admin_id, expected_version, reason, request_id
):
    if not actor.is_superuser:
        raise PermissionDenied
    clean_reason = validate_safe_plain_text(
        reason, field_label="归属变更原因", max_length=200, required=False
    )
    if customer.is_staff or customer.is_superuser:
        raise NotFound
    try:
        owner = (
            AdminProfile.objects.select_for_update()
            .select_related("user", "role")
            .get(
                pk=owner_admin_id,
                admin_status=AdminProfile.Status.ACTIVE,
                user__is_active=True,
                user__is_staff=True,
                user__is_superuser=False,
                role__isnull=False,
                role__status=AdminRole.Status.ACTIVE,
            )
        )
    except AdminProfile.DoesNotExist as exc:
        raise NotFound from exc
    try:
        assignment = CustomerAssignment.objects.select_for_update().get(customer=customer)
    except CustomerAssignment.DoesNotExist as exc:
        raise NotFound from exc
    if assignment.version != expected_version:
        raise AssignmentVersionConflict from None
    before = {
        "version": assignment.version,
        "owner_admin_id": str(assignment.owner_admin_id),
    }
    assignment.owner_admin = owner
    assignment.assigned_by = actor
    assignment.assigned_at = timezone.now()
    assignment.version += 1
    assignment.full_clean()
    assignment.save()
    _event(
        actor=actor,
        target=assignment,
        target_type="assignment",
        event_type="customer_assignment_changed",
        before=before,
        after={
            "version": assignment.version,
            "owner_admin_id": str(owner.pk),
            "reason_provided": bool(clean_reason),
        },
        request_id=request_id,
    )
    return assignment
