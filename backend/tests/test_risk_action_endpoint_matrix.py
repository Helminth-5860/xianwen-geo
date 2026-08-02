import uuid
from collections.abc import Callable
from dataclasses import dataclass

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.admin_rbac.models import (
    AdminPermission,
    AdminProfile,
    AdminRole,
    ApprovalRequest,
    CustomerAssignment,
    RiskPolicy,
)
from apps.admin_rbac.permissions import resolve_admin_context
from apps.admin_rbac.risk_catalog import RISK_ACTION_BY_KEY
from apps.admin_rbac.services import create_admin
from apps.plans.application_services import create_application
from apps.plans.models import Plan, PlanApplication, PlanVersion
from apps.plans.serializers import limit_value
from apps.plans.services import (
    create_plan,
    create_plan_version,
    publish_plan_version,
    set_plan_offline,
)
from apps.plans.subscription_services import grant_trial
from apps.quotas.idempotency import derive_idempotency_digests
from apps.quotas.models import QuotaAccount
from apps.quotas.services import adjust_quota_account
from apps.users.models import User
from tests.admin_session_helpers import authenticate_admin_client
from tests.test_subscriptions import published_plan

PASSWORD = "Correct-Horse-Battery-2026!"
MODES = ("confirm", "password", "two_person")


@dataclass
class EndpointCase:
    path: str
    method: str
    body: dict
    snapshot: Callable[[], object]
    headers: dict | None = None


def superuser(phone):
    return User.objects.create_superuser(phone=phone, nickname="超级管理员", password=PASSWORD)


def admin_client(user):
    return authenticate_admin_client(APIClient(), user)


def send(client, case, body):
    return getattr(client, case.method)(case.path, body, format="json", **(case.headers or {}))


def plan_fixture(actor, *, code, publish=False, offline=False):
    plan = create_plan(
        plan_id=uuid.uuid4(),
        actor=actor,
        data={
            "code": code,
            "name": "风险矩阵套餐",
            "description": "",
            "price_display_mode": "fixed",
            "display_price": "99.00",
            "is_trial": False,
            "sort_order": 10,
        },
    )
    if not publish:
        return plan, None
    version = create_plan_version(
        plan_id=plan.pk,
        actor=actor,
        expected_plan_version=plan.version,
    )
    version = publish_plan_version(
        version_id=version.pk,
        actor=actor,
        expected_version=version.version,
        confirm_informal_composite=True,
    )
    plan.refresh_from_db()
    if offline:
        plan = set_plan_offline(
            plan_id=plan.pk,
            actor=actor,
            expected_version=plan.version,
        )
    return plan, version


def version_update_body(version):
    return {
        "expected_version": version.version,
        "valid_days": version.valid_days + 1,
        "queue_priority": version.queue_priority,
        "limits": [
            {"key": item.limit_key, "value": limit_value(item)}
            for item in version.limits.order_by("limit_key")
        ],
        "model_permissions": [
            {
                "model_key": item.model_key,
                "sort_order": item.sort_order,
                "selected_by_default": item.selected_by_default,
            }
            for item in version.model_permissions.order_by("sort_order", "model_key")
        ],
    }


def build_plan_case(action_key, actor):
    suffix = action_key.replace(".", "-")
    if action_key == "plan.create":
        code = "matrix-create"
        return EndpointCase(
            "/api/v1/admin/plans",
            "post",
            {
                "code": code,
                "name": "矩阵创建套餐",
                "description": "",
                "price_display_mode": "contact",
                "display_price": None,
                "is_trial": False,
                "sort_order": 1,
            },
            lambda: Plan.objects.filter(code=code).count(),
        )

    if action_key == "plan.update":
        plan, _ = plan_fixture(actor, code=suffix)
        return EndpointCase(
            f"/api/v1/admin/plans/{plan.pk}",
            "patch",
            {"expected_version": plan.version, "name": "更新后的套餐"},
            lambda: tuple(Plan.objects.filter(pk=plan.pk).values_list("name", "version")),
        )

    if action_key == "plan.copy":
        source, version = plan_fixture(actor, code=suffix, publish=True)
        return EndpointCase(
            f"/api/v1/admin/plans/{source.pk}/copy",
            "post",
            {
                "new_code": "matrix-copy-target",
                "new_name": "矩阵复制套餐",
                "source_version_id": str(version.pk),
                "expected_source_plan_version": source.version,
            },
            lambda: Plan.objects.filter(code="matrix-copy-target").count(),
        )

    if action_key == "plan.version.create":
        plan, _ = plan_fixture(actor, code=suffix)
        return EndpointCase(
            f"/api/v1/admin/plans/{plan.pk}/versions",
            "post",
            {"expected_plan_version": plan.version},
            lambda: PlanVersion.objects.filter(plan=plan).count(),
        )

    if action_key == "plan.version.update":
        plan, _ = plan_fixture(actor, code=suffix)
        version = create_plan_version(
            plan_id=plan.pk,
            actor=actor,
            expected_plan_version=plan.version,
        )
        return EndpointCase(
            f"/api/v1/admin/plan-versions/{version.pk}",
            "patch",
            version_update_body(version),
            lambda: tuple(
                PlanVersion.objects.filter(pk=version.pk).values_list("valid_days", "version")
            ),
        )

    if action_key == "plan.version.publish":
        plan, _ = plan_fixture(actor, code=suffix)
        version = create_plan_version(
            plan_id=plan.pk,
            actor=actor,
            expected_plan_version=plan.version,
        )
        return EndpointCase(
            f"/api/v1/admin/plan-versions/{version.pk}/publish",
            "post",
            {
                "expected_version": version.version,
                "confirm_informal_composite": True,
            },
            lambda: tuple(
                PlanVersion.objects.filter(pk=version.pk).values_list("status", "version")
            ),
        )

    if action_key == "plan.offline":
        plan, _ = plan_fixture(actor, code=suffix, publish=True)
        return EndpointCase(
            f"/api/v1/admin/plans/{plan.pk}/offline",
            "post",
            {"expected_version": plan.version},
            lambda: tuple(Plan.objects.filter(pk=plan.pk).values_list("status", "version")),
        )

    if action_key == "plan.online":
        plan, _ = plan_fixture(actor, code=suffix, publish=True, offline=True)
        return EndpointCase(
            f"/api/v1/admin/plans/{plan.pk}/online",
            "post",
            {"expected_version": plan.version},
            lambda: tuple(Plan.objects.filter(pk=plan.pk).values_list("status", "version")),
        )

    if action_key == "plan.archive":
        plan, _ = plan_fixture(actor, code=suffix)
        return EndpointCase(
            f"/api/v1/admin/plans/{plan.pk}/archive",
            "post",
            {"expected_version": plan.version},
            lambda: tuple(Plan.objects.filter(pk=plan.pk).values_list("status", "version")),
        )

    if action_key == "plan.version.retire":
        plan, _ = plan_fixture(actor, code=suffix)
        version = create_plan_version(
            plan_id=plan.pk,
            actor=actor,
            expected_plan_version=plan.version,
        )
        return EndpointCase(
            f"/api/v1/admin/plan-versions/{version.pk}/retire",
            "post",
            {"expected_version": version.version},
            lambda: tuple(
                PlanVersion.objects.filter(pk=version.pk).values_list("status", "version")
            ),
        )

    raise AssertionError(action_key)


def build_plan_application_case(action_key, actor):
    plan, version = plan_fixture(actor, code=action_key.replace(".", "-"), publish=True)
    applicant = User.objects.create_user(
        phone="13800138000", nickname="套餐申请用户", password=PASSWORD
    )
    application = create_application(
        applicant=applicant,
        plan_id=plan.pk,
        plan_version_id=version.pk,
        user_note="",
        idempotency_key=f"matrix-{action_key.replace('.', '-')}-key",
        request_id=uuid.uuid4(),
    ).application
    action = action_key.rsplit(".", 1)[-1]
    return EndpointCase(
        f"/api/v1/admin/plan-applications/{application.pk}/{action}",
        "post",
        {"expected_version": application.version},
        lambda: tuple(
            PlanApplication.objects.filter(pk=application.pk).values_list("status", "version")
        ),
    )


def build_quota_case(action_key, actor):
    customer = User.objects.create_user(
        phone="13800138000",
        nickname="Quota target",
        password=PASSWORD,
        approval_status=User.ApprovalStatus.APPROVED,
    )
    plan, _ = published_plan(
        actor,
        code=f"matrix-{action_key.replace('.', '-')}",
        trial=True,
    )
    subscription = grant_trial(
        requester=actor,
        admin_context=resolve_admin_context(actor),
        user_id=customer.pk,
        expected_status_version=customer.status_version,
        plan_id=plan.pk,
        opening_note="",
        request_id=uuid.uuid4(),
    )
    account = QuotaAccount.objects.get(
        subscription=subscription,
        quota_type="detection_points",
    )
    setup_reason = "risk matrix setup"
    setup_digests = derive_idempotency_digests(
        f"matrix-setup-{account.pk}",
        operation="grant",
        user_id=account.user_id,
        account_id=account.pk,
        business_type="quota_adjustment",
        business_id=account.pk,
        request_payload={"amount": 5, "reason": setup_reason},
    )
    adjust_quota_account(
        requester=actor,
        admin_context=resolve_admin_context(actor),
        account_id=account.pk,
        expected_version=account.version,
        action="grant",
        amount=5,
        reason=setup_reason,
        digests=setup_digests,
        request_id=uuid.uuid4(),
    )
    account.refresh_from_db()
    endpoint_action = action_key.removeprefix("quota.").replace("_", "-")
    return EndpointCase(
        f"/api/v1/admin/quota-accounts/{account.pk}/adjust/{endpoint_action}",
        "post",
        {
            "expected_version": account.version,
            "amount": 1,
            "reason": "risk matrix adjustment",
        },
        lambda: tuple(
            QuotaAccount.objects.filter(pk=account.pk).values_list(
                "available", "frozen", "version", "ledger_sequence"
            )
        ),
        {"HTTP_IDEMPOTENCY_KEY": f"matrix-{endpoint_action}-key-0001"},
    )


def build_case(action_key, actor):
    if action_key.startswith("quota."):
        return build_quota_case(action_key, actor)
    if action_key.startswith("plan."):
        return build_plan_case(action_key, actor)
    if action_key.startswith("plan_application."):
        return build_plan_application_case(action_key, actor)

    target_role = AdminRole.objects.create(
        name=f"目标角色-{action_key}", data_scope=AdminRole.DataScope.ALL
    )
    replacement_role = AdminRole.objects.create(
        name=f"替换角色-{action_key}", data_scope=AdminRole.DataScope.ALL
    )
    target_admin = create_admin(
        actor_id=actor.pk,
        phone="13600136000",
        nickname="目标管理员",
        password=PASSWORD,
        role_id=target_role.pk,
        request_id=uuid.uuid4(),
    )
    customer = User.objects.create_user(phone="13800138000", nickname="目标客户", password=PASSWORD)

    if action_key == "admin.disable":
        return EndpointCase(
            f"/api/v1/admin/admins/{target_admin.id}/disable",
            "post",
            {"expected_version": target_admin.version},
            lambda: (
                AdminProfile.objects.get(pk=target_admin.pk).admin_status,
                User.objects.get(pk=target_admin.user_id).is_staff,
            ),
        )
    if action_key == "admin.lock":
        return EndpointCase(
            f"/api/v1/admin/admins/{target_admin.id}/lock",
            "post",
            {"expected_version": target_admin.version},
            lambda: AdminProfile.objects.get(pk=target_admin.pk).admin_status,
        )
    if action_key == "admin.role.change":
        return EndpointCase(
            f"/api/v1/admin/admins/{target_admin.id}/role",
            "post",
            {
                "expected_version": target_admin.version,
                "role_id": str(replacement_role.pk),
            },
            lambda: AdminProfile.objects.get(pk=target_admin.pk).role_id,
        )
    if action_key == "admin.force_logout":
        return EndpointCase(
            f"/api/v1/admin/admins/{target_admin.id}/force-logout",
            "post",
            {"expected_version": target_admin.version},
            lambda: User.objects.get(pk=target_admin.user_id).session_version,
        )
    if action_key == "role.permissions.replace":
        permission = AdminPermission.objects.get(key="users.list")
        return EndpointCase(
            f"/api/v1/admin/roles/{replacement_role.id}/permissions",
            "put",
            {
                "expected_version": replacement_role.version,
                "permission_keys": [permission.key],
            },
            lambda: (
                AdminRole.objects.get(pk=replacement_role.pk).version,
                tuple(
                    replacement_role.permission_links.order_by("permission__key").values_list(
                        "permission__key", flat=True
                    )
                ),
            ),
        )
    if action_key == "role.disable":
        return EndpointCase(
            f"/api/v1/admin/roles/{replacement_role.id}/disable",
            "post",
            {"expected_version": replacement_role.version},
            lambda: AdminRole.objects.get(pk=replacement_role.pk).status,
        )
    if action_key == "role.security.update":
        return EndpointCase(
            f"/api/v1/admin/roles/{replacement_role.id}/security",
            "patch",
            {
                "expected_security_version": replacement_role.security_version,
                "require_sms_2fa": True,
                "confirm_lockout": False,
            },
            lambda: (
                AdminRole.objects.get(pk=replacement_role.pk).security_version,
                AdminRole.objects.get(pk=replacement_role.pk).require_sms_2fa,
            ),
        )
    if action_key == "role.ip_allowlist.update":
        return EndpointCase(
            f"/api/v1/admin/roles/{replacement_role.id}/ip-allowlist",
            "post",
            {
                "expected_security_version": replacement_role.security_version,
                "network_cidr": "203.0.113.44/32",
                "label": "运维出口",
                "confirm_lockout": False,
            },
            lambda: (
                AdminRole.objects.get(pk=replacement_role.pk).security_version,
                tuple(
                    replacement_role.ip_allowlist_entries.order_by("id").values_list(
                        "network_cidr", flat=True
                    )
                ),
            ),
        )
    if action_key == "superuser.ip_allowlist.update":
        policy = actor.superuser_security_policy
        return EndpointCase(
            "/api/v1/admin/security/superuser/ip-allowlist",
            "post",
            {
                "expected_security_version": policy.security_version,
                "network_cidr": "203.0.113.45/32",
                "label": "超级管理员出口",
                "confirm_lockout": False,
            },
            lambda: (
                actor.superuser_security_policy.__class__.objects.get(
                    pk=policy.pk
                ).security_version,
                tuple(
                    policy.ip_allowlist_entries.order_by("id").values_list(
                        "network_cidr", flat=True
                    )
                ),
            ),
        )
    if action_key == "customer.assignment.change":
        return EndpointCase(
            f"/api/v1/admin/users/{customer.id}/assignment",
            "put",
            {
                "expected_version": 0,
                "owner_admin_id": str(target_admin.id),
                "reason": "分配负责人",
            },
            lambda: tuple(
                CustomerAssignment.objects.filter(customer=customer).values_list(
                    "owner_admin_id", "version"
                )
            ),
        )
    if action_key == "user.freeze":
        return EndpointCase(
            f"/api/v1/admin/users/{customer.id}/freeze",
            "post",
            {"expected_version": customer.status_version, "reason": "安全冻结"},
            lambda: (
                User.objects.get(pk=customer.pk).account_status,
                User.objects.get(pk=customer.pk).status_version,
            ),
        )
    if action_key == "user.review.reject":
        return EndpointCase(
            f"/api/v1/admin/users/{customer.id}/review",
            "post",
            {
                "decision": "reject",
                "expected_version": customer.status_version,
                "reason": "资料不完整",
            },
            lambda: (
                User.objects.get(pk=customer.pk).approval_status,
                User.objects.get(pk=customer.pk).status_version,
            ),
        )
    raise AssertionError(action_key)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "action_key",
    sorted(key for key in RISK_ACTION_BY_KEY if not key.startswith("subscription.")),
)
@pytest.mark.parametrize("mode", MODES)
def test_each_existing_high_risk_endpoint_enforces_policy_without_bypass(action_key, mode):
    requester = superuser("13900139000")
    cache.clear()
    approver = superuser("13700137000")
    case = build_case(action_key, requester)
    policy = RiskPolicy.objects.get(action_id=action_key)
    policy.current_mode = mode
    policy.version += 1
    policy.save(update_fields=["current_mode", "version", "updated_at"])
    before = case.snapshot()
    client = admin_client(requester)
    definition = RISK_ACTION_BY_KEY[action_key]

    if mode not in definition.supported_modes:
        body = {
            **case.body,
            "current_password": PASSWORD,
        }
        response = send(client, case, body)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "RISK_SECURITY_MODE_NOT_SUPPORTED"
        assert case.snapshot() == before
        return

    if mode == "confirm":
        missing = send(client, case, dict(case.body))
        assert missing.status_code == 422
        assert missing.json()["error"]["code"] == "RISK_CONFIRMATION_REQUIRED"
        assert case.snapshot() == before
        response = send(client, case, {**case.body, "confirmed": True})
    elif mode == "password":
        missing = send(client, case, dict(case.body))
        assert missing.status_code == 422
        assert case.snapshot() == before
        wrong = send(
            client,
            case,
            {**case.body, "current_password": "Wrong-Password-2026!"},
        )
        assert wrong.status_code == 403
        assert wrong.json()["error"]["code"] == "ADMIN_REAUTH_FAILED"
        assert case.snapshot() == before
        response = send(
            client,
            case,
            {**case.body, "current_password": PASSWORD},
        )
    else:
        response = send(
            client,
            case,
            {
                **case.body,
                "confirmed": True,
                "current_password": PASSWORD,
            },
        )
        assert response.status_code == 202
        data = response.json()["data"]
        assert set(data) == {
            "approval_required",
            "approval_id",
            "status",
            "expires_at",
        }
        assert data["approval_required"] is True
        assert data["status"] == "pending"
        assert case.snapshot() == before
        approval = ApprovalRequest.objects.get(pk=data["approval_id"])
        approved = admin_client(approver).post(
            f"/api/v1/admin/approvals/{approval.id}/approve",
            {"current_password": PASSWORD},
            format="json",
        )
        assert approved.status_code == 200
        approval.refresh_from_db()
        assert approval.status == ApprovalRequest.Status.EXECUTED
        assert case.snapshot() != before
        replay = admin_client(approver).post(
            f"/api/v1/admin/approvals/{approval.id}/approve",
            {"current_password": PASSWORD},
            format="json",
        )
        assert replay.status_code == 409
        return

    assert response.status_code in {200, 201}
    assert case.snapshot() != before
    assert ApprovalRequest.objects.count() == 0
