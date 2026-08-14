import hashlib
import uuid
from datetime import time, timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from apps.keywords.exceptions import (
    KeywordPlanRequired,
    KeywordStateConflict,
    KeywordSubjectVersionConflict,
    KeywordVersionConflict,
    KeywordVersionNoChanges,
)
from apps.keywords.models import Keyword, KeywordSet, KeywordSetVersion
from apps.keywords.normalization import KeywordNormalizationError, normalize_keyword_items
from apps.keywords.services import commit_keyword_version, save_keyword_draft
from apps.plans.models import Plan, PlanVersion, Subscription
from apps.subjects.models import Subject, SubjectName, SubjectType, SubjectVersion
from apps.subjects.schema_snapshots import (
    build_schema_snapshot,
    materialize_defaults,
    values_digest,
)
from apps.users.models import User

pytestmark = pytest.mark.django_db
PASSWORD = "Correct-Horse-Battery-2026!"


@pytest.fixture(autouse=True)
def seed_subject_catalog():
    call_command("sync_subject_catalog", "--apply", verbosity=0)


def make_facts(*, status=Subject.Status.DRAFT, with_plan=True):
    suffix = uuid.uuid4().hex[:10]
    user = User.objects.create_user(
        phone=f"139{uuid.uuid4().int % 100000000:08d}",
        nickname="Keyword user",
        password=PASSWORD,
        approval_status=User.ApprovalStatus.APPROVED,
        account_status=User.AccountStatus.ACTIVE,
    )
    subject_type = SubjectType.objects.get(key="enterprise")
    snapshot, digest = build_schema_snapshot(subject_type)
    values = materialize_defaults(snapshot)
    values["name"] = "示例企业"
    subject = Subject.objects.create(
        user=user,
        subject_type=subject_type,
        status=status,
        draft_values=values,
        schema_version=subject_type.schema_version,
        schema_snapshot_format_version=1,
        schema_snapshot=snapshot,
        schema_digest=digest,
    )
    subject_version = SubjectVersion.objects.create(
        subject=subject,
        version_no=1,
        field_values=values,
        schema_version=subject.schema_version,
        schema_snapshot_format_version=subject.schema_snapshot_format_version,
        schema_snapshot=snapshot,
        schema_digest=digest,
        field_values_digest=values_digest(values),
        semantic_digest=hashlib.sha256(b"keyword-subject-v1").hexdigest(),
        official_name="示例企业",
        created_by=user,
    )
    SubjectName.objects.create(
        subject_version=subject_version,
        role=SubjectName.Role.OFFICIAL_NAME,
        display_value="示例企业",
        matching_value="示例企业".casefold(),
        source_field_key="name",
    )
    subject.current_version = subject_version
    subject.version += 1
    subject.save(update_fields=["current_version", "version", "updated_at"])
    if with_plan:
        now = timezone.now()
        plan = Plan.objects.create(
            code=f"keyword-{suffix}",
            name="Keyword plan",
            is_trial=True,
            status=Plan.Status.PUBLISHED,
        )
        plan_version = PlanVersion.objects.create(
            plan=plan,
            version_no=1,
            status=PlanVersion.Status.PUBLISHED,
            valid_days=30,
            queue_priority=1,
            effective_config={"limits": {}},
            config_digest="a" * 64,
            snapshot_generated_at=now,
            published_at=now,
        )
        Subscription.objects.create(
            user=user,
            source_type=Subscription.SourceType.TRIAL_GRANT,
            plan=plan,
            plan_version=plan_version,
            plan_version_no=1,
            entitlement_snapshot={"limits": {}},
            entitlement_digest="b" * 64,
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=10),
            cycle_anchor_day=now.day,
            cycle_anchor_time=time(0, 0),
            is_trial=True,
            activated_at=now,
            request_id=uuid.uuid4(),
        )
    return user, subject, subject_version


def sample_items():
    return [
        {
            "text": "  GEO　Optimization  ",
            "structure_type": "short",
            "is_regional": False,
            "region_level": "",
            "region_text": "",
        },
        {
            "text": "企业 GEO 服务",
            "structure_type": "long_tail",
            "is_regional": True,
            "region_level": "city",
            "region_text": " 上海 ",
        },
    ]


def test_normalization_collapses_nfkc_whitespace_case_and_regions():
    rows = normalize_keyword_items(sample_items())
    assert rows[0].text == "GEO Optimization"
    assert rows[0].matching_text == "geo optimization"
    assert rows[1].region_text == "上海"
    assert rows[1].region_matching_key == "city:上海"


def test_casefold_expansion_respects_storage_limit():
    with pytest.raises(KeywordNormalizationError):
        normalize_keyword_items(
            [{"text": "ß" * 500, "structure_type": "general", "is_regional": False}]
        )


def test_duplicate_semantics_ignore_structure_type():
    items = [
        {"text": "Geo", "structure_type": "short", "is_regional": False},
        {"text": "ＧＥＯ", "structure_type": "general", "is_regional": False},
    ]
    with pytest.raises(KeywordNormalizationError):
        normalize_keyword_items(items)


def test_region_shape_requires_text_and_rejects_nonregional_region_fields():
    with pytest.raises(KeywordNormalizationError):
        normalize_keyword_items(
            [
                {
                    "text": "上海 GEO",
                    "structure_type": "long_tail",
                    "is_regional": True,
                    "region_level": "city",
                    "region_text": "",
                }
            ]
        )
    with pytest.raises(KeywordNormalizationError):
        normalize_keyword_items(
            [
                {
                    "text": "GEO",
                    "structure_type": "short",
                    "is_regional": False,
                    "region_text": "上海",
                }
            ]
        )


def test_save_noop_commit_and_no_change():
    user, subject, subject_version = make_facts()
    keyword_set, created = save_keyword_draft(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=0,
        expected_subject_version_id=subject_version.pk,
        items=sample_items(),
    )
    assert created is True
    assert keyword_set.version == 1
    same, changed = save_keyword_draft(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=1,
        expected_subject_version_id=subject_version.pk,
        items=sample_items(),
    )
    assert changed is False
    assert same.version == 1

    keyword_set, version = commit_keyword_version(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=1,
        expected_subject_version_id=subject_version.pk,
    )
    assert version.version_no == 1
    assert keyword_set.current_version == version
    assert list(version.keywords.values_list("sort_order", flat=True)) == [0, 1]
    assert keyword_set.version == 2
    with pytest.raises(KeywordVersionNoChanges):
        commit_keyword_version(
            user_id=user.pk,
            subject_id=subject.pk,
            expected_version=2,
            expected_subject_version_id=subject_version.pk,
        )


def test_active_subject_allows_writes_and_stale_aggregate_version_conflicts():
    user, subject, subject_version = make_facts(status=Subject.Status.ACTIVE)
    keyword_set, _ = save_keyword_draft(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=0,
        expected_subject_version_id=subject_version.pk,
        items=sample_items(),
    )
    assert keyword_set.version == 1
    with pytest.raises(KeywordVersionConflict):
        save_keyword_draft(
            user_id=user.pk,
            subject_id=subject.pk,
            expected_version=0,
            expected_subject_version_id=subject_version.pk,
            items=sample_items(),
        )


def test_subject_version_change_requires_explicit_rebase():
    user, subject, first = make_facts()
    keyword_set, _ = save_keyword_draft(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=0,
        expected_subject_version_id=first.pk,
        items=sample_items(),
    )
    second = SubjectVersion.objects.create(
        subject=subject,
        version_no=2,
        field_values=first.field_values,
        schema_version=first.schema_version,
        schema_snapshot_format_version=first.schema_snapshot_format_version,
        schema_snapshot=first.schema_snapshot,
        schema_digest=first.schema_digest,
        field_values_digest=first.field_values_digest,
        semantic_digest=hashlib.sha256(b"keyword-subject-v2").hexdigest(),
        official_name=first.official_name,
        created_by=user,
    )
    SubjectName.objects.create(
        subject_version=second,
        role=SubjectName.Role.OFFICIAL_NAME,
        display_value=first.official_name,
        matching_value=first.official_name.casefold(),
        source_field_key="name",
    )
    subject.current_version = second
    subject.version += 1
    subject.save(update_fields=["current_version", "version", "updated_at"])

    with pytest.raises(KeywordSubjectVersionConflict):
        save_keyword_draft(
            user_id=user.pk,
            subject_id=subject.pk,
            expected_version=keyword_set.version,
            expected_subject_version_id=first.pk,
            items=sample_items(),
        )

    rebased, changed = save_keyword_draft(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=keyword_set.version,
        expected_subject_version_id=second.pk,
        items=sample_items(),
    )
    assert changed is True
    assert rebased.draft_subject_version == second
    assert rebased.version == 2


def test_same_keywords_can_create_new_formal_version_after_subject_version_changes():
    user, subject, first = make_facts()
    keyword_set, _ = save_keyword_draft(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=0,
        expected_subject_version_id=first.pk,
        items=sample_items(),
    )
    keyword_set, first_keywords = commit_keyword_version(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=keyword_set.version,
        expected_subject_version_id=first.pk,
    )

    second = SubjectVersion.objects.create(
        subject=subject,
        version_no=2,
        field_values=first.field_values,
        schema_version=first.schema_version,
        schema_snapshot_format_version=first.schema_snapshot_format_version,
        schema_snapshot=first.schema_snapshot,
        schema_digest=first.schema_digest,
        field_values_digest=first.field_values_digest,
        semantic_digest=hashlib.sha256(b"keyword-subject-rebase").hexdigest(),
        official_name=first.official_name,
        created_by=user,
    )
    SubjectName.objects.create(
        subject_version=second,
        role=SubjectName.Role.OFFICIAL_NAME,
        display_value=first.official_name,
        matching_value=first.official_name.casefold(),
        source_field_key="name",
    )
    subject.current_version = second
    subject.version += 1
    subject.save(update_fields=["current_version", "version", "updated_at"])

    keyword_set, changed = save_keyword_draft(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=keyword_set.version,
        expected_subject_version_id=second.pk,
        items=sample_items(),
    )
    assert changed is True
    keyword_set, second_keywords = commit_keyword_version(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=keyword_set.version,
        expected_subject_version_id=second.pk,
    )
    assert second_keywords.version_no == first_keywords.version_no + 1
    assert second_keywords.content_digest != first_keywords.content_digest


def test_archived_and_missing_plan_block_writes():
    user, subject, version = make_facts(status=Subject.Status.ARCHIVED)
    with pytest.raises(KeywordStateConflict):
        save_keyword_draft(
            user_id=user.pk,
            subject_id=subject.pk,
            expected_version=0,
            expected_subject_version_id=version.pk,
            items=sample_items(),
        )

    user2, subject2, version2 = make_facts(with_plan=False)
    with pytest.raises(KeywordPlanRequired):
        save_keyword_draft(
            user_id=user2.pk,
            subject_id=subject2.pk,
            expected_version=0,
            expected_subject_version_id=version2.pk,
            items=sample_items(),
        )


def test_get_draft_is_side_effect_free():
    user, subject, _ = make_facts()
    client = APIClient()
    client.force_authenticate(user)
    response = client.get(f"/api/v1/subjects/{subject.pk}/keywords/draft")
    assert response.status_code == 200
    assert response.json()["data"]["version"] == 0
    assert KeywordSet.objects.filter(subject=subject).exists() is False


def test_api_is_owner_scoped_strict_and_does_not_expose_internal_keys():
    user, subject, version = make_facts()
    client = APIClient()
    client.force_authenticate(user)
    response = client.patch(
        f"/api/v1/subjects/{subject.pk}/keywords/draft",
        {
            "expected_version": 0,
            "expected_subject_version_id": str(version.pk),
            "items": sample_items(),
        },
        format="json",
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["version"] == 1
    assert "matching_text" not in payload["items"][0]
    assert "region_matching_key" not in payload["items"][1]

    forged = client.patch(
        f"/api/v1/subjects/{subject.pk}/keywords/draft",
        {
            "expected_version": 1,
            "expected_subject_version_id": str(version.pk),
            "items": sample_items(),
            "current_version": "forged",
        },
        format="json",
    )
    assert forged.status_code == 422

    other = User.objects.create_user(
        phone=f"137{uuid.uuid4().int % 100000000:08d}",
        nickname="Other",
        password=PASSWORD,
        approval_status=User.ApprovalStatus.APPROVED,
    )
    other_client = APIClient()
    other_client.force_authenticate(other)
    assert other_client.get(f"/api/v1/subjects/{subject.pk}/keywords/draft").status_code == 404


def test_keyword_draft_write_requires_real_csrf():
    user, subject, version = make_facts()
    client = APIClient(enforce_csrf_checks=True)
    client.force_authenticate(user)
    blocked = client.patch(
        f"/api/v1/subjects/{subject.pk}/keywords/draft",
        {
            "expected_version": 0,
            "expected_subject_version_id": str(version.pk),
            "items": sample_items(),
        },
        format="json",
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "CSRF_FAILED"


def test_formal_models_are_append_only_at_orm_layer():
    user, subject, version = make_facts()
    keyword_set, _ = save_keyword_draft(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=0,
        expected_subject_version_id=version.pk,
        items=sample_items(),
    )
    _, formal = commit_keyword_version(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=keyword_set.version,
        expected_subject_version_id=version.pk,
    )
    with pytest.raises(TypeError):
        KeywordSetVersion.objects.filter(pk=formal.pk).update(item_count=99)
    with pytest.raises(TypeError):
        Keyword.objects.filter(keyword_set_version=formal).delete()
