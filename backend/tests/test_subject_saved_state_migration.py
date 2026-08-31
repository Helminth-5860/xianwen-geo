import json
from importlib import import_module

import pytest
from django.apps import apps
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.subjects.models import Subject, SubjectContext, SubjectType
from apps.users.models import User
from tests.subject_risk_helpers import install_empty_published_risk_catalog


@pytest.mark.django_db
def test_saved_subject_data_migration_promotes_usable_rows_and_repairs_context():
    call_command("sync_subject_catalog", "--apply", verbosity=0)
    install_empty_published_risk_catalog()
    user = User.objects.create_user(
        phone="13800138088",
        nickname="Migration subject user",
        password="Correct-Horse-Battery-2026!",
        account_status=User.AccountStatus.ACTIVE,
    )
    subject_type = SubjectType.objects.get(key="enterprise")
    client = APIClient()
    client.force_authenticate(user)
    created = client.post(
        "/api/v1/subjects",
        {
            "subject_type_id": str(subject_type.pk),
            "expected_schema_version": subject_type.schema_version,
            "initial_values": {"name": "历史已保存主体"},
        },
        format="json",
    ).json()["data"]
    saved = client.put(
        f"/api/v1/subjects/{created['id']}",
        {
            "expected_version": created["version"],
            "values": {
                **created["draft_values"],
                "target_audience": "企业客户",
                "service_regions": json.dumps(
                    {"version": 1, "nationwide": True, "areas": []},
                    ensure_ascii=False,
                ),
            },
            "profile_values": {
                "legal_entity_type": "company",
                "contact_name": "张三",
                "contact_phone": "0755-12345678",
                "business_address": json.dumps(
                    {
                        "version": 1,
                        "path": [
                            {"code": "440000", "name": "广东省"},
                            {"code": "440300", "name": "深圳市"},
                            {"code": "440305", "name": "南山区"},
                        ],
                        "detail": "示例路 1 号",
                    },
                    ensure_ascii=False,
                ),
                "industry": "企业服务",
                "primary_business": "企业 GEO 服务",
                "brand_name": "",
                "social_channels": {},
            },
        },
        format="json",
    ).json()["data"]["subject"]
    subject = Subject.objects.get(pk=saved["id"])
    Subject.objects.filter(pk=subject.pk).update(status=Subject.Status.DRAFT)
    user.is_test_account = True
    user.save(update_fields=["is_test_account", "updated_at"])
    unsaved = client.post(
        "/api/v1/subjects",
        {
            "subject_type_id": str(subject_type.pk),
            "expected_schema_version": subject_type.schema_version,
            "initial_values": {"name": "尚未保存主体"},
        },
        format="json",
    ).json()["data"]
    context = SubjectContext.objects.get(user=user)
    context.current_subject_id = unsaved["id"]
    context.save(update_fields=["current_subject", "updated_at"])

    migration = import_module("apps.subjects.migrations.0017_promote_saved_subjects")
    migration.promote_saved_subjects(apps, None)

    subject.refresh_from_db()
    context.refresh_from_db()
    assert subject.status == Subject.Status.ACTIVE
    assert context.current_subject_id == subject.pk
