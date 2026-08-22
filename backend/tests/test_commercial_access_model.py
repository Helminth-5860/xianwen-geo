import pytest
from rest_framework.exceptions import NotFound
from rest_framework.test import APIClient

from apps.admin_rbac.commercial_policy import TENANT_ADMIN_BASELINE_PERMISSIONS
from apps.admin_rbac.models import AdminProfile, AdminRole
from apps.admin_rbac.permissions import resolve_admin_context
from apps.admin_rbac.risk_catalog import SMS_STEP_UP_REQUIRED_ACTIONS
from apps.admin_rbac.scopes import scoped_customers
from apps.admin_rbac.services import assign_customer
from apps.articles.models import Article
from apps.geo.models import GeoDetectionJob, GeoReport
from apps.images.models import ImageAsset
from apps.subjects.models import Subject
from apps.users.commercial import CommercialIdentity, commercial_home_route, commercial_identity
from apps.users.models import Tenant, User
from apps.users.serializers import CurrentUserSerializer
from tests.admin_session_helpers import authenticate_admin_client

PASSWORD = "Correct-Horse-Battery-2026!"


def tenant(key: str, name: str) -> Tenant:
    return Tenant.objects.create(key=key, display_name=name, brand_name=f"{name}品牌")


def user(phone: str, tenant_obj: Tenant, *, staff: bool = False) -> User:
    return User.objects.create_user(
        phone=phone,
        nickname=phone[-4:],
        password=PASSWORD,
        tenant=tenant_obj,
        is_staff=staff,
        approval_status=User.ApprovalStatus.APPROVED,
    )


@pytest.mark.django_db
def test_three_commercial_identities_have_stable_home_routes_and_branding():
    first = tenant("first", "第一租户")
    end_user = user("13800001001", first)
    role = AdminRole.objects.create(name="租户管理员", data_scope=AdminRole.DataScope.OWN)
    tenant_admin = user("13800001002", first, staff=True)
    AdminProfile.objects.create(user=tenant_admin, role=role)
    super_admin = User.objects.create_superuser(
        phone="13800001003", nickname="平台管理员", password=PASSWORD
    )

    assert commercial_identity(end_user) == CommercialIdentity.END_USER
    assert commercial_home_route(end_user) == "/workspace"
    assert commercial_identity(tenant_admin) == CommercialIdentity.TENANT_ADMIN
    assert commercial_home_route(tenant_admin) == "/admin"
    assert commercial_identity(super_admin) == CommercialIdentity.PLATFORM_SUPER_ADMIN
    assert commercial_home_route(super_admin) == "/admin"

    payload = CurrentUserSerializer(end_user).data
    assert payload["home_route"] == "/workspace"
    assert payload["tenant"]["brand_name"] == "第一租户品牌"


@pytest.mark.django_db
def test_tenant_admin_gets_operational_pages_without_fine_role_grants_but_not_platform_secrets():
    first = tenant("first", "第一租户")
    role = AdminRole.objects.create(name="空权限租户角色", data_scope=AdminRole.DataScope.OWN)
    tenant_admin = user("13800002001", first, staff=True)
    AdminProfile.objects.create(user=tenant_admin, role=role)

    context = resolve_admin_context(tenant_admin)
    assert context is not None
    assert context.identity == CommercialIdentity.TENANT_ADMIN
    assert TENANT_ADMIN_BASELINE_PERMISSIONS <= context.permission_keys
    assert {
        "menu.admin.users",
        "menu.admin.plan-applications",
        "menu.admin.subscriptions",
        "menu.admin.quotas",
        "menu.admin.operations",
    } <= context.menu_keys
    assert "menu.admin.admins" not in context.menu_keys
    assert "menu.admin.models" not in context.menu_keys
    assert "api_credentials.manage" not in context.permission_keys
    assert "quotas.adjust" not in context.permission_keys


@pytest.mark.django_db
def test_tenant_scope_is_the_boundary_for_all_user_owned_business_domains():
    first = tenant("first", "第一租户")
    second = tenant("second", "第二租户")
    role = AdminRole.objects.create(name="租户运营", data_scope=AdminRole.DataScope.ALL)
    tenant_admin = user("13800003001", first, staff=True)
    AdminProfile.objects.create(user=tenant_admin, role=role)
    first_user = user("13800003002", first)
    second_user = user("13800003003", second)

    context = resolve_admin_context(tenant_admin)
    assert context is not None
    visible_ids = set(scoped_customers(tenant_admin, context).values_list("id", flat=True))
    assert first_user.id in visible_ids
    assert second_user.id not in visible_ids

    # Every requested business domain inherits the same boundary through its
    # protected User foreign key; no plan or quota field participates in scope.
    for model in (Subject, GeoDetectionJob, GeoReport, Article, ImageAsset):
        owner_field = model._meta.get_field("user")
        assert owner_field.remote_field.model is User


@pytest.mark.django_db
def test_tenant_internal_assignment_cannot_bind_an_admin_from_another_tenant():
    first = tenant("first", "第一租户")
    second = tenant("second", "第二租户")
    role = AdminRole.objects.create(name="租户运营", data_scope=AdminRole.DataScope.OWN)
    first_admin = user("13800003501", first, staff=True)
    first_profile = AdminProfile.objects.create(user=first_admin, role=role)
    second_admin = user("13800003502", second, staff=True)
    second_profile = AdminProfile.objects.create(user=second_admin, role=role)
    first_customer = user("13800003503", first)
    context = resolve_admin_context(first_admin)
    assert context is not None

    with pytest.raises(NotFound):
        assign_customer(
            actor=first_admin,
            context=context,
            customer=first_customer,
            owner_admin_id=second_profile.id,
            expected_version=0,
            reason="不得跨租户分配",
            request_id=first_profile.id,
        )


@pytest.mark.django_db
def test_super_admin_has_global_catalog_and_tenant_admin_quota_visibility_is_not_execution():
    super_admin = User.objects.create_superuser(
        phone="13800004001", nickname="平台管理员", password=PASSWORD
    )
    context = resolve_admin_context(super_admin)
    assert context is not None
    assert context.identity == CommercialIdentity.PLATFORM_SUPER_ADMIN
    assert "menu.admin.admins" in context.menu_keys
    assert "api_credentials.manage" in context.permission_keys

    assert "quotas.list" in TENANT_ADMIN_BASELINE_PERMISSIONS
    assert "quotas.ledger.view" in TENANT_ADMIN_BASELINE_PERMISSIONS
    assert "quotas.adjust" not in TENANT_ADMIN_BASELINE_PERMISSIONS
    assert {"quota.grant", "quota.compensate", "quota.manual_deduct"} <= (
        SMS_STEP_UP_REQUIRED_ACTIONS
    )


@pytest.mark.django_db
def test_tenant_management_is_super_admin_only_and_keeps_step_up_enforcement():
    super_admin = User.objects.create_superuser(
        phone="13800005001", nickname="平台管理员", password=PASSWORD
    )
    without_step_up = authenticate_admin_client(APIClient(), super_admin, step_up=False)
    denied = without_step_up.post(
        "/api/v1/admin/tenants",
        {
            "key": "step-up-denied",
            "display_name": "不能创建",
            "brand_name": "",
            "logo_reference": "",
            "status": "active",
        },
        format="json",
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "ADMIN_STEP_UP_REQUIRED"

    with_step_up = authenticate_admin_client(APIClient(), super_admin, step_up=True)
    created = with_step_up.post(
        "/api/v1/admin/tenants",
        {
            "key": "step-up-allowed",
            "display_name": "已创建租户",
            "brand_name": "租户品牌",
            "logo_reference": "",
            "status": "active",
        },
        format="json",
    )
    assert created.status_code == 201
    assert created.json()["data"]["key"] == "step-up-allowed"
