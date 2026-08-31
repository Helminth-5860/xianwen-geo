import json

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.subjects.models import SubjectBusinessProfile, SubjectType
from apps.users.models import User
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
