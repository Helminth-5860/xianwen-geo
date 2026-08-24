import uuid

import pytest
from django.core.exceptions import ValidationError
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.test import APIClient

from apps.admin_rbac.commercial_policy import ADMIN_BASELINE_PERMISSIONS
from apps.admin_rbac.models import AdminRole, CustomerAssignment
from apps.admin_rbac.permissions import resolve_admin_context
from apps.admin_rbac.registration_links import issue_registration_ref
from apps.admin_rbac.risk_catalog import SMS_STEP_UP_REQUIRED_ACTIONS
from apps.admin_rbac.scopes import scoped_customer_or_404, scoped_customers
from apps.admin_rbac.services import assign_customer, create_admin
from apps.articles.models import Article
from apps.geo.models import GeoDetectionJob, GeoReport
from apps.images.models import ImageAsset
from apps.subjects.models import Subject
from apps.users.commercial import CommercialIdentity, commercial_home_route, commercial_identity
from apps.users.models import Tenant, User
from apps.users.serializers import CurrentUserSerializer, RegistrationSerializer
from apps.users.services import create_registered_user
from tests.admin_session_helpers import authenticate_admin_client

PASSWORD = "Correct-Horse-Battery-2026!"


def tenant(key: str, name: str) -> Tenant:
    return Tenant.objects.create(key=key, display_name=name, brand_name=f"{name}品牌")


def user(phone: str, tenant_obj: Tenant | None = None, *, staff: bool = False) -> User:
    return User.objects.create_user(
        phone=phone,
        nickname=phone[-4:],
        password=PASSWORD,
        tenant=tenant_obj,
        is_staff=staff,
    )


def admin(super_admin, role, phone, tenant_obj=None):
    return create_admin(
        actor_id=super_admin.id,
        phone=phone,
        nickname=phone[-4:],
        password=PASSWORD,
        role_id=role.id,
        tenant_id=tenant_obj.id if tenant_obj else None,
        request_id=uuid.uuid4(),
    )


@pytest.mark.django_db
def test_three_commercial_identities_have_stable_home_routes_and_branding():
    first = tenant("first", "第一租户")
    super_admin = User.objects.create_superuser(
        phone="13800001003", nickname="平台管理员", password=PASSWORD
    )
    role = AdminRole.objects.create(name="代理管理员", data_scope=AdminRole.DataScope.OWN)
    owner = admin(super_admin, role, "13800001002", first)
    end_user = user("13800001001", first)
    CustomerAssignment.objects.create(customer=end_user, owner_admin=owner)

    assert commercial_identity(end_user) == CommercialIdentity.USER
    assert commercial_home_route(end_user) == "/workspace"
    assert commercial_identity(owner.user) == CommercialIdentity.ADMIN
    assert commercial_home_route(owner.user) == "/admin"
    assert commercial_identity(super_admin) == CommercialIdentity.SUPER_ADMIN
    assert commercial_home_route(super_admin) == "/admin"

    payload = CurrentUserSerializer(end_user).data
    assert payload["home_route"] == "/workspace"
    assert payload["tenant"]["brand_name"] == "第一租户品牌"


@pytest.mark.django_db
def test_admin_gets_operational_pages_without_super_admin_capabilities():
    super_admin = User.objects.create_superuser(
        phone="13800002000", nickname="平台管理员", password=PASSWORD
    )
    role = AdminRole.objects.create(name="代理角色", data_scope=AdminRole.DataScope.ALL)
    profile = admin(super_admin, role, "13800002001")

    context = resolve_admin_context(profile.user)
    assert context is not None
    assert context.identity == CommercialIdentity.ADMIN
    assert ADMIN_BASELINE_PERMISSIONS <= context.permission_keys
    assert "menu.admin.admins" not in context.menu_keys
    assert "api_credentials.manage" not in context.permission_keys
    assert "quotas.adjust" not in context.permission_keys


@pytest.mark.django_db
def test_customer_assignment_is_the_boundary_for_all_user_owned_business_domains():
    first = tenant("first", "第一租户")
    second = tenant("second", "第二租户")
    super_admin = User.objects.create_superuser(
        phone="13800003000", nickname="平台管理员", password=PASSWORD
    )
    role = AdminRole.objects.create(name="代理运营", data_scope=AdminRole.DataScope.ALL)
    first_admin = admin(super_admin, role, "13800003001", first)
    second_admin = admin(super_admin, role, "13800003004", second)
    first_user = user("13800003002", first)
    second_user = user("13800003003", first)
    CustomerAssignment.objects.create(customer=first_user, owner_admin=first_admin)
    CustomerAssignment.objects.create(customer=second_user, owner_admin=second_admin)

    context = resolve_admin_context(first_admin.user)
    visible_ids = set(scoped_customers(first_admin.user, context).values_list("id", flat=True))
    assert visible_ids == {first_user.id}

    # Tenant equality and role data_scope=ALL cannot widen direct ownership.
    with pytest.raises(NotFound):
        scoped_customer_or_404(first_admin.user, context, second_user.id)

    # Every requested business domain inherits the same boundary through its
    # protected User foreign key; plans and quota fields do not alter scope.
    for model in (Subject, GeoDetectionJob, GeoReport, Article, ImageAsset):
        assert model._meta.get_field("user").remote_field.model is User


@pytest.mark.django_db
def test_only_super_admin_can_reassign_admin_owned_users():
    super_admin = User.objects.create_superuser(
        phone="13800003500", nickname="平台管理员", password=PASSWORD
    )
    role = AdminRole.objects.create(name="代理运营", data_scope=AdminRole.DataScope.ALL)
    first = admin(super_admin, role, "13800003501")
    second = admin(super_admin, role, "13800003502")
    customer = user("13800003503")
    assignment = CustomerAssignment.objects.create(customer=customer, owner_admin=first)

    with pytest.raises(PermissionDenied):
        assign_customer(
            actor=first.user,
            context=resolve_admin_context(first.user),
            customer=customer,
            owner_admin_id=second.id,
            expected_version=assignment.version,
            reason="ADMIN 不得变更归属",
            request_id=uuid.uuid4(),
        )

    changed = assign_customer(
        actor=super_admin,
        context=resolve_admin_context(super_admin),
        customer=customer,
        owner_admin_id=second.id,
        expected_version=assignment.version,
        reason="平台重新分配",
        request_id=uuid.uuid4(),
    )
    assert changed.owner_admin == second


@pytest.mark.django_db
def test_admin_cannot_create_admin_even_with_broad_role_scope():
    super_admin = User.objects.create_superuser(
        phone="13800003600", nickname="平台管理员", password=PASSWORD
    )
    role = AdminRole.objects.create(name="全范围代理", data_scope=AdminRole.DataScope.ALL)
    profile = admin(super_admin, role, "13800003601")
    client = authenticate_admin_client(APIClient(), profile.user, step_up=True)

    response = client.post(
        "/api/v1/admin/admins",
        {
            "phone": "13800003602",
            "nickname": "禁止创建",
            "password": PASSWORD,
            "role_id": str(role.id),
        },
        format="json",
    )
    assert response.status_code == 403
    assert not User.objects.filter(phone="+8613800003602").exists()


@pytest.mark.django_db
def test_user_cannot_create_admin_or_submit_role_upgrade_fields():
    super_admin = User.objects.create_superuser(
        phone="13800003610", nickname="平台管理员", password=PASSWORD
    )
    role = AdminRole.objects.create(name="直属代理", data_scope=AdminRole.DataScope.OWN)
    owner = admin(super_admin, role, "13800003611")
    customer = user("13800003612")
    CustomerAssignment.objects.create(customer=customer, owner_admin=owner)

    client = APIClient()
    client.force_authenticate(customer)
    denied = client.post(
        "/api/v1/admin/admins",
        {
            "phone": "13800003613",
            "nickname": "禁止升级",
            "password": PASSWORD,
            "role_id": str(role.id),
        },
        format="json",
    )
    assert denied.status_code == 403

    serializer = RegistrationSerializer(
        data={
            "phone": "13800003614",
            "nickname": "恶意注册字段",
            "sms_code": "123456",
            "password": PASSWORD,
            "ref": issue_registration_ref(owner),
            "is_staff": True,
            "role_id": str(role.id),
        }
    )
    assert serializer.is_valid() is False
    assert {"is_staff", "role_id"} <= set(serializer.errors)


@pytest.mark.django_db
def test_user_registration_cannot_upgrade_role_and_supports_optional_admin_assignment():
    default_tenant = Tenant.legacy_default()
    super_admin = User.objects.create_superuser(
        phone="13800003700", nickname="平台管理员", password=PASSWORD
    )
    role = AdminRole.objects.create(name="默认代理", data_scope=AdminRole.DataScope.OWN)
    owner = admin(super_admin, role, "13800003701", default_tenant)
    registration_ref = issue_registration_ref(owner)

    created = create_registered_user(
        phone="+8613800003702",
        nickname="企业客户",
        password=PASSWORD,
        registration_ref=registration_ref,
    )

    assert commercial_identity(created) == CommercialIdentity.USER
    assert created.is_staff is False
    assert created.is_superuser is False
    assert created.customer_assignment.owner_admin == owner
    assert CustomerAssignment.objects.filter(customer=created).count() == 1

    independent = create_registered_user(
        phone="+8613800003703",
        nickname="独立企业客户",
        password=PASSWORD,
    )
    assert commercial_identity(independent) == CommercialIdentity.USER
    assert independent.is_staff is False
    assert independent.is_superuser is False
    assert independent.customer_assignment.owner_admin is None


@pytest.mark.django_db
def test_super_admin_cannot_be_a_direct_customer_owner():
    super_admin = User.objects.create_superuser(
        phone="13800003800", nickname="平台管理员", password=PASSWORD
    )
    customer = user("13800003801")
    assignment = CustomerAssignment(customer=customer, owner_admin=super_admin.admin_profile)

    with pytest.raises(ValidationError):
        assignment.full_clean()


@pytest.mark.django_db
def test_independent_user_login_succeeds_without_admin_assignment():
    independent = user("13800003802")
    client = APIClient(enforce_csrf_checks=True)
    csrf = client.get("/api/v1/auth/csrf").json()["data"]["csrf_token"]

    response = client.post(
        "/api/v1/auth/login/password",
        {"phone": independent.phone, "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )

    assert response.status_code == 200
    assert response.json()["data"]["home_route"] == "/workspace"


@pytest.mark.django_db
def test_super_admin_has_global_customer_visibility_and_admin_does_not():
    super_admin = User.objects.create_superuser(
        phone="13800004001", nickname="平台管理员", password=PASSWORD
    )
    role = AdminRole.objects.create(name="代理", data_scope=AdminRole.DataScope.ALL)
    first = admin(super_admin, role, "13800004002")
    second = admin(super_admin, role, "13800004003")
    first_customer = user("13800004004")
    second_customer = user("13800004005")
    CustomerAssignment.objects.create(customer=first_customer, owner_admin=first)
    CustomerAssignment.objects.create(customer=second_customer, owner_admin=second)

    admin_ids = set(
        scoped_customers(first.user, resolve_admin_context(first.user)).values_list("id", flat=True)
    )
    super_ids = set(
        scoped_customers(super_admin, resolve_admin_context(super_admin)).values_list(
            "id", flat=True
        )
    )
    assert admin_ids == {first_customer.id}
    assert {first_customer.id, second_customer.id} <= super_ids
    super_context = resolve_admin_context(super_admin)
    assert "menu.admin.admins" in super_context.menu_keys
    assert "api_credentials.manage" in super_context.permission_keys
    assert "quotas.list" in ADMIN_BASELINE_PERMISSIONS
    assert "quotas.ledger.view" in ADMIN_BASELINE_PERMISSIONS
    assert "quotas.adjust" not in ADMIN_BASELINE_PERMISSIONS
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
