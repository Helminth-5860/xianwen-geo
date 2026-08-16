import uuid

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.admin_rbac.models import AuditEvent
from apps.questions.catalog import BUILTIN_QUESTION_CATEGORIES
from apps.questions.models import QuestionCategory, QuestionTag
from apps.subjects.models import SubjectType
from apps.users.models import User
from tests.admin_session_helpers import authenticate_admin_client

PASSWORD = "Correct-Horse-Battery-2026!"


@pytest.fixture(autouse=True)
def synchronize_catalogs():
    call_command("sync_admin_rbac", "--apply", verbosity=0)
    call_command("sync_subject_catalog", "--apply", verbosity=0)


def make_user(*, phone="13800138000", account="active"):
    return User.objects.create_user(
        phone=phone,
        nickname="问题分类用户",
        password=PASSWORD,
        approval_status=User.ApprovalStatus.APPROVED,
        account_status=account,
    )


def make_admin():
    suffix = User.objects.count() + 1
    return User.objects.create_superuser(
        phone=f"139{suffix:08d}", nickname="问题分类管理员", password=PASSWORD
    )


def admin_client(*, csrf=False):
    client = APIClient(enforce_csrf_checks=csrf)
    return authenticate_admin_client(client, make_admin())


def api_data(response):
    return response.json()["data"]


@pytest.mark.django_db
def test_seed_contains_exact_builtin_categories_and_no_invented_tags():
    assert list(QuestionCategory.objects.order_by("sort_order").values_list("key", flat=True)) == [
        item.key for item in BUILTIN_QUESTION_CATEGORIES
    ]
    assert QuestionCategory.objects.filter(is_builtin=True, status="active").count() == 10
    assert QuestionTag.objects.count() == 0
    assert all(not row.applicable_subject_types.exists() for row in QuestionCategory.objects.all())


@pytest.mark.django_db
def test_admin_creates_normalized_category_with_applicability_and_safe_audit():
    enterprise = SubjectType.objects.get(key="enterprise")
    response = admin_client().post(
        "/api/v1/admin/question-categories",
        {
            "key": "service_process",
            "name": "  服务   流程  ",
            "description": "  服务流程说明  ",
            "generation_guidance": "  生成办理流程相关问题  ",
            "sort_order": 120,
            "applicable_subject_type_ids": [str(enterprise.id)],
        },
        format="json",
    )

    assert response.status_code == 201
    data = api_data(response)
    assert data["name"] == "服务 流程"
    assert data["applicable_subject_type_ids"] == [str(enterprise.id)]
    assert data["can_delete"] is False
    category = QuestionCategory.objects.get(pk=data["id"])
    assert category.normalized_name == "服务 流程".casefold()
    event = AuditEvent.objects.get(
        category="question_catalog",
        action_key="question_category.create",
        target_id=category.id,
    )
    serialized = str(event.safe_after)
    assert "服务流程说明" not in serialized
    assert "生成办理流程" not in serialized


@pytest.mark.django_db
def test_duplicate_casefold_name_invalid_key_unknown_field_and_duplicate_subject_are_rejected():
    client = admin_client()
    created = client.post(
        "/api/v1/admin/question-tags",
        {"key": "decision", "name": "Decision"},
        format="json",
    )
    assert created.status_code == 201
    duplicate = client.post(
        "/api/v1/admin/question-tags",
        {"key": "decision_2", "name": "ＤＥＣＩＳＩＯＮ"},
        format="json",
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "QUESTION_CATALOG_DUPLICATE"
    invalid_key = client.post(
        "/api/v1/admin/question-tags",
        {"key": "Not-Valid", "name": "无效键"},
        format="json",
    )
    assert invalid_key.status_code == 422
    assert invalid_key.json()["error"]["code"] == "QUESTION_CATALOG_VALUES_INVALID"
    unknown = client.post(
        "/api/v1/admin/question-tags",
        {"key": "unknown_field", "name": "未知字段", "delete": True},
        format="json",
    )
    assert unknown.status_code == 422
    subject_type = SubjectType.objects.get(key="enterprise")
    duplicate_subject = client.post(
        "/api/v1/admin/question-tags",
        {
            "key": "duplicate_subject",
            "name": "重复主体",
            "applicable_subject_type_ids": [str(subject_type.id), str(subject_type.id)],
        },
        format="json",
    )
    assert duplicate_subject.status_code == 422


@pytest.mark.django_db
def test_update_and_status_use_expected_version_and_machine_key_is_not_patchable():
    client = admin_client()
    category = QuestionCategory.objects.get(key="brand_awareness")
    updated = client.patch(
        f"/api/v1/admin/question-categories/{category.id}",
        {
            "expected_version": category.version,
            "name": "品牌认知度",
            "sort_order": 11,
        },
        format="json",
    )
    assert updated.status_code == 200
    assert api_data(updated)["version"] == 2
    stale = client.patch(
        f"/api/v1/admin/question-categories/{category.id}",
        {"expected_version": 1, "description": "不会保存"},
        format="json",
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "QUESTION_CATALOG_VERSION_CONFLICT"
    machine = client.patch(
        f"/api/v1/admin/question-categories/{category.id}",
        {"expected_version": 2, "key": "changed"},
        format="json",
    )
    assert machine.status_code == 422
    disabled = client.post(
        f"/api/v1/admin/question-categories/{category.id}/disable",
        {"expected_version": 2},
        format="json",
    )
    assert disabled.status_code == 200
    assert api_data(disabled)["status"] == "inactive"
    same = client.post(
        f"/api/v1/admin/question-categories/{category.id}/disable",
        {"expected_version": 3},
        format="json",
    )
    assert same.status_code == 409
    assert same.json()["error"]["code"] == "QUESTION_CATALOG_STATE_CONFLICT"


@pytest.mark.django_db
def test_public_catalog_returns_only_active_and_applicable_rows():
    enterprise = SubjectType.objects.get(key="enterprise")
    brand = SubjectType.objects.get(key="brand")
    restricted = QuestionCategory.objects.create(
        key="enterprise_only",
        name="企业专用",
        normalized_name="企业专用",
        description="",
        generation_guidance="",
        sort_order=5,
    )
    restricted.applicable_subject_types.add(enterprise)
    hidden = QuestionTag.objects.create(
        key="hidden",
        name="隐藏标签",
        normalized_name="隐藏标签",
        status="inactive",
    )
    visible = QuestionTag.objects.create(
        key="universal", name="通用标签", normalized_name="通用标签", status="active"
    )
    assert hidden and visible
    client = APIClient()
    client.force_authenticate(make_user())

    enterprise_data = api_data(
        client.get("/api/v1/question-categories", {"subject_type_id": str(enterprise.id)})
    )
    brand_data = api_data(
        client.get("/api/v1/question-categories", {"subject_type_id": str(brand.id)})
    )
    assert restricted.key in {row["key"] for row in enterprise_data["categories"]}
    assert restricted.key not in {row["key"] for row in brand_data["categories"]}
    assert {row["key"] for row in enterprise_data["tags"]} == {"universal"}
    assert "status" not in enterprise_data["categories"][0]


@pytest.mark.django_db
def test_public_catalog_rejects_unknown_query_and_unavailable_subject_type():
    client = APIClient()
    client.force_authenticate(make_user())
    unknown = client.get("/api/v1/question-categories", {"extra": "value"})
    assert unknown.status_code == 422
    missing = client.get("/api/v1/question-categories", {"subject_type_id": uuid.uuid4()})
    assert missing.status_code == 404
    inactive = SubjectType.objects.get(key="enterprise")
    inactive.status = SubjectType.Status.INACTIVE
    inactive.save(update_fields=["status", "updated_at"])
    unavailable = client.get("/api/v1/question-categories", {"subject_type_id": str(inactive.id)})
    assert unavailable.status_code == 404


@pytest.mark.django_db
def test_admin_catalog_requires_admin_permission_csrf_and_has_no_delete_api():
    user_client = APIClient()
    user_client.force_authenticate(make_user())
    assert user_client.get("/api/v1/admin/question-categories").status_code == 403

    csrf_client = admin_client(csrf=True)
    blocked = csrf_client.post(
        "/api/v1/admin/question-tags",
        {"key": "csrf", "name": "CSRF"},
        format="json",
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "CSRF_FAILED"

    category = QuestionCategory.objects.get(key="brand_awareness")
    no_delete = admin_client().delete(f"/api/v1/admin/question-categories/{category.id}")
    assert no_delete.status_code == 403
    assert QuestionCategory.objects.filter(pk=category.id).exists()


@pytest.mark.django_db
def test_question_catalog_permissions_are_seeded_and_synced():
    from apps.admin_rbac.catalog import CATALOG_BY_KEY
    from apps.admin_rbac.models import AdminPermission

    expected = {
        "menu.admin.question-categories",
        "question_categories.list",
        "question_categories.create",
        "question_categories.update",
        "question_categories.disable",
        "question_tags.list",
        "question_tags.create",
        "question_tags.update",
        "question_tags.disable",
    }
    assert expected <= set(CATALOG_BY_KEY)
    assert expected <= set(AdminPermission.objects.values_list("key", flat=True))
