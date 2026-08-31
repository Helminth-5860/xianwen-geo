import json

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.subjects.models import Subject, SubjectBusinessProfile, SubjectType
from apps.users.models import Tenant, User
from tests.subject_risk_helpers import install_empty_published_risk_catalog

PASSWORD = "Correct-Horse-Battery-2026!"


@pytest.fixture(autouse=True)
def seed_subject_catalog():
    call_command("sync_subject_catalog", "--apply", verbosity=0)


def client_for_user():
    user = User.objects.create_user(
        phone="13800138991",
        nickname="主体管理测试",
        password=PASSWORD,
        account_status=User.AccountStatus.ACTIVE,
    )
    client = APIClient()
    client.force_authenticate(user)
    return client


def response_data(response):
    return response.json()["data"]


def structured_address():
    return json.dumps(
        {
            "version": 1,
            "path": [
                {"code": "440000", "name": "广东省"},
                {"code": "440100", "name": "广州市"},
                {"code": "440106", "name": "天河区"},
            ],
            "detail": "体育西路 101 号",
        },
        ensure_ascii=False,
    )


def nationwide_coverage():
    return json.dumps(
        {"version": 1, "nationwide": True, "areas": []},
        ensure_ascii=False,
    )


def create_subject(client, *, name="广州显问网络科技有限公司"):
    subject_type = SubjectType.objects.get(key="enterprise")
    response = client.post(
        "/api/v1/subjects",
        {
            "subject_type_id": str(subject_type.pk),
            "expected_schema_version": subject_type.schema_version,
            "initial_values": {"name": name},
        },
        format="json",
    )
    assert response.status_code == 201
    return response_data(response)


def complete_values(subject):
    return {
        **subject["draft_values"],
        "target_audience": "广州市中小企业",
        "service_regions": nationwide_coverage(),
    }


def complete_profile():
    return {
        "business_address": structured_address(),
        "industry": "企业软件服务",
        "primary_business": "企业 GEO 分析与内容优化服务",
        "contact_name": "",
        "contact_phone": "",
        "brand_name": "",
        "subject_aliases": "",
        "unified_social_credit_code": "",
        "social_channels": {},
    }


@pytest.mark.django_db
def test_public_subject_types_match_the_product_catalog():
    client = client_for_user()
    response = client.get("/api/v1/subject-types")

    assert response.status_code == 200
    rows = response_data(response)
    assert [row["name"] for row in rows] == [
        "企业 / 公司",
        "个体工商户",
        "品牌",
        "产品 / 服务",
        "个人IP / 人物",
        "机构 / 组织",
        "项目",
        "景区 / 景点",
        "其他",
    ]
    assert not SubjectType.objects.filter(
        key__in=("store", "service", "professional_institution"), status="active"
    ).exists()


@pytest.mark.django_db
def test_complete_core_profile_saves_and_reports_seventy_percent():
    install_empty_published_risk_catalog()
    client = client_for_user()
    subject = create_subject(client)

    response = client.put(
        f"/api/v1/subjects/{subject['id']}",
        {
            "expected_version": subject["version"],
            "values": complete_values(subject),
            "profile_values": complete_profile(),
        },
        format="json",
    )

    assert response.status_code == 200
    saved = response_data(response)["subject"]
    assert saved["status"] == "active"
    assert saved["profile_completeness"] == {
        "percentage": 70,
        "core_completed": 7,
        "core_total": 7,
        "missing_core": [],
        "suggestion": "建议补充官方网站，有助于提升主体识别与 GEO 分析质量。",
    }
    profile = SubjectBusinessProfile.objects.get(subject_id=subject["id"])
    assert profile.legal_entity_type == "company"
    assert profile.industry == "企业软件服务"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("profile_patch", "values_patch", "missing_field"),
    [
        ({"business_address": "广东省广州市天河区体育西路 101 号"}, {}, "business_address"),
        (
            {},
            {
                "service_regions": json.dumps(
                    {
                        "version": 1,
                        "nationwide": False,
                        "areas": [
                            {
                                "code": "440106",
                                "name": "天河区",
                                "level": "district",
                                "path": [
                                    {"code": "440000", "name": "广东省"},
                                    {"code": "440100", "name": "广州市"},
                                    {"code": "440106", "name": "天河区"},
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
            },
            "service_regions",
        ),
    ],
)
def test_invalid_address_or_business_coverage_cannot_activate_subject(
    profile_patch, values_patch, missing_field
):
    install_empty_published_risk_catalog()
    client = client_for_user()
    subject = create_subject(client)

    response = client.put(
        f"/api/v1/subjects/{subject['id']}",
        {
            "expected_version": subject["version"],
            "values": {**complete_values(subject), **values_patch},
            "profile_values": {**complete_profile(), **profile_patch},
        },
        format="json",
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SUBJECT_FIELD_VALUES_INVALID"
    assert missing_field in response.json()["error"]["details"]["fields"]
    assert not SubjectBusinessProfile.objects.filter(subject_id=subject["id"]).exists()


@pytest.mark.django_db
def test_bound_subject_is_unique_identity_locked_and_operating_profile_remains_editable():
    install_empty_published_risk_catalog()
    tenant = Tenant.objects.create(key="single-subject-test", display_name="单主体测试空间")
    owner = User.objects.create_user(
        phone="13800138992",
        nickname="主体负责人",
        password=PASSWORD,
        account_status=User.AccountStatus.ACTIVE,
        tenant=tenant,
    )
    colleague = User.objects.create_user(
        phone="13800138993",
        nickname="主体同事",
        password=PASSWORD,
        account_status=User.AccountStatus.ACTIVE,
        tenant=tenant,
    )
    owner_client = APIClient()
    owner_client.force_authenticate(owner)
    colleague_client = APIClient()
    colleague_client.force_authenticate(colleague)

    draft = create_subject(owner_client)
    bound_response = owner_client.put(
        f"/api/v1/subjects/{draft['id']}",
        {
            "expected_version": draft["version"],
            "values": complete_values(draft),
            "profile_values": complete_profile(),
        },
        format="json",
    )
    assert bound_response.status_code == 200
    bound = response_data(bound_response)["subject"]
    assert bound["identity_bound"] is True
    assert Subject.objects.get(pk=bound["id"]).tenant_id == tenant.pk

    duplicate = colleague_client.post(
        "/api/v1/subjects",
        {
            "subject_type_id": str(SubjectType.objects.get(key="enterprise").pk),
            "expected_schema_version": SubjectType.objects.get(key="enterprise").schema_version,
            "initial_values": {"name": "第二个主体"},
        },
        format="json",
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "SUBJECT_LIMIT_REACHED"
    assert duplicate.json()["error"]["message"] == "当前工作空间已绑定主体，不允许新增其他主体。"

    changed_identity = owner_client.put(
        f"/api/v1/subjects/{bound['id']}",
        {
            "expected_version": bound["version"],
            "values": {**bound["draft_values"], "name": "另一家公司"},
            "profile_values": bound["business_profile"],
        },
        format="json",
    )
    assert changed_identity.status_code == 409
    assert changed_identity.json()["error"]["code"] == "SUBJECT_IDENTITY_LOCKED"

    changed_credit = owner_client.put(
        f"/api/v1/subjects/{bound['id']}",
        {
            "expected_version": bound["version"],
            "values": bound["draft_values"],
            "profile_values": {
                **bound["business_profile"],
                "unified_social_credit_code": "91440101MA5ABCDE12",
            },
        },
        format="json",
    )
    assert changed_credit.status_code == 409
    assert changed_credit.json()["error"]["code"] == "SUBJECT_IDENTITY_LOCKED"

    updated = owner_client.put(
        f"/api/v1/subjects/{bound['id']}",
        {
            "expected_version": bound["version"],
            "values": bound["draft_values"],
            "profile_values": {**bound["business_profile"], "industry": "人工智能服务"},
        },
        format="json",
    )
    assert updated.status_code == 200
    updated_subject = response_data(updated)["subject"]
    assert updated_subject["id"] == bound["id"]
    assert updated_subject["business_profile"]["industry"] == "人工智能服务"
    assert Subject.objects.filter(tenant=tenant).count() == 1

    archive = owner_client.post(
        f"/api/v1/subjects/{bound['id']}/archive",
        {"expected_version": updated_subject["version"]},
        format="json",
    )
    assert archive.status_code == 409

    colleague_list = colleague_client.get("/api/v1/subjects")
    assert colleague_list.status_code == 200
    assert [row["id"] for row in response_data(colleague_list)["subjects"]] == [bound["id"]]

    colleague_versions = colleague_client.get(f"/api/v1/subjects/{bound['id']}/versions")
    assert colleague_versions.status_code == 200
    assert len(response_data(colleague_versions)["versions"]) == 1
