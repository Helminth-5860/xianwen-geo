import hashlib
import uuid
from datetime import time, timedelta

import pytest
from django.core.management import call_command
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from apps.keywords.models import Keyword, KeywordSetVersion
from apps.keywords.services import commit_keyword_version, save_keyword_draft
from apps.plans.models import Plan, PlanVersion, Subscription
from apps.subjects.models import Subject, SubjectName, SubjectType, SubjectVersion
from apps.subjects.schema_snapshots import (
    build_schema_snapshot,
    materialize_defaults,
    values_digest,
)
from apps.users.models import User

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="PostgreSQL keyword guard tests require PostgreSQL.",
    ),
]


@pytest.fixture(autouse=True)
def seed_subject_catalog():
    call_command("sync_subject_catalog", "--apply", verbosity=0)


def facts():
    suffix = uuid.uuid4().hex[:10]
    user = User.objects.create_user(
        phone=f"136{uuid.uuid4().int % 100000000:08d}",
        nickname="Keyword pg",
        password="Correct-Horse-Battery-2026!",
        account_status=User.AccountStatus.ACTIVE,
    )
    subject_type = SubjectType.objects.get(key="enterprise")
    snapshot, digest = build_schema_snapshot(subject_type)
    values = materialize_defaults(snapshot)
    values["name"] = "关键词 PostgreSQL 主体"
    with transaction.atomic():
        subject = Subject.objects.create(
            user=user,
            subject_type=subject_type,
            status=Subject.Status.DRAFT,
            draft_values=values,
            schema_version=subject_type.schema_version,
            schema_snapshot_format_version=1,
            schema_snapshot=snapshot,
            schema_digest=digest,
        )
        version = SubjectVersion.objects.create(
            subject=subject,
            version_no=1,
            field_values=values,
            schema_version=subject.schema_version,
            schema_snapshot_format_version=1,
            schema_snapshot=snapshot,
            schema_digest=digest,
            field_values_digest=values_digest(values),
            semantic_digest=hashlib.sha256(b"keyword-pg-subject").hexdigest(),
            official_name="关键词 PostgreSQL 主体",
            created_by=user,
        )
        SubjectName.objects.create(
            subject_version=version,
            role=SubjectName.Role.OFFICIAL_NAME,
            display_value="关键词 PostgreSQL 主体",
            matching_value="关键词 PostgreSQL 主体".casefold(),
            source_field_key="name",
        )
        subject.current_version = version
        subject.version += 1
        subject.save(update_fields=["current_version", "version", "updated_at"])
    now = timezone.now()
    plan = Plan.objects.create(
        code=f"keyword-pg-{suffix}",
        name="Keyword pg plan",
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
    keyword_set, _ = save_keyword_draft(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=0,
        expected_subject_version_id=version.pk,
        items=[
            {"text": "GEO", "structure_type": "short", "is_regional": False},
            {
                "text": "上海 GEO",
                "structure_type": "long_tail",
                "is_regional": True,
                "region_level": "city",
                "region_text": "上海",
            },
        ],
    )
    keyword_set, formal = commit_keyword_version(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=keyword_set.version,
        expected_subject_version_id=version.pk,
    )
    return user, subject, version, keyword_set, formal


def test_formal_version_and_keyword_are_database_immutable():
    _, _, _, _, formal = facts()
    keyword = formal.keywords.first()
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE keyword_set_versions SET item_count = item_count + 1 WHERE id = %s",
                [formal.pk],
            )
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM keywords WHERE id = %s", [keyword.pk])


def test_finalized_version_rejects_appending_keyword():
    _, _, _, _, formal = facts()
    with pytest.raises(DatabaseError), transaction.atomic():
        Keyword.objects.create(
            keyword_set_version=formal,
            text="不能追加",
            matching_text="不能追加",
            structure_type="general",
            is_regional=False,
            region_level="",
            region_text="",
            region_matching_key="",
            sort_order=99,
        )


def test_raw_next_version_without_current_pointer_fails_at_commit():
    user, subject, subject_version, keyword_set, formal = facts()
    with pytest.raises(DatabaseError), transaction.atomic():
        next_version = KeywordSetVersion.objects.create(
            keyword_set=keyword_set,
            user=user,
            subject=subject,
            subject_version=subject_version,
            version_no=formal.version_no + 1,
            content_digest="c" * 64,
            item_count=1,
            created_by=user,
        )
        Keyword.objects.create(
            keyword_set_version=next_version,
            text="新版本",
            matching_text="新版本",
            structure_type="general",
            is_regional=False,
            region_level="",
            region_text="",
            region_matching_key="",
            sort_order=0,
        )


def test_historical_version_rejects_appending_keyword_after_newer_version_exists():
    user, subject, subject_version, keyword_set, first = facts()
    keyword_set, _ = save_keyword_draft(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=keyword_set.version,
        expected_subject_version_id=subject_version.pk,
        items=[{"text": "第二版", "structure_type": "general", "is_regional": False}],
    )
    _, second = commit_keyword_version(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=keyword_set.version,
        expected_subject_version_id=subject_version.pk,
    )
    assert second.version_no == first.version_no + 1
    with pytest.raises(DatabaseError), transaction.atomic():
        Keyword.objects.create(
            keyword_set_version=first,
            text="历史追加",
            matching_text="历史追加",
            structure_type="general",
            is_regional=False,
            region_level="",
            region_text="",
            region_matching_key="",
            sort_order=first.item_count,
        )


def test_raw_formal_version_must_bind_current_subject_version():
    user, subject, first_subject_version, keyword_set, formal = facts()
    with transaction.atomic():
        second_subject_version = SubjectVersion.objects.create(
            subject=subject,
            version_no=2,
            field_values=first_subject_version.field_values,
            schema_version=first_subject_version.schema_version,
            schema_snapshot_format_version=first_subject_version.schema_snapshot_format_version,
            schema_snapshot=first_subject_version.schema_snapshot,
            schema_digest=first_subject_version.schema_digest,
            field_values_digest=first_subject_version.field_values_digest,
            semantic_digest=hashlib.sha256(b"keyword-pg-subject-v2").hexdigest(),
            official_name=first_subject_version.official_name,
            created_by=user,
        )
        SubjectName.objects.create(
            subject_version=second_subject_version,
            role=SubjectName.Role.OFFICIAL_NAME,
            display_value=first_subject_version.official_name,
            matching_value=first_subject_version.official_name.casefold(),
            source_field_key="name",
        )
        subject.current_version = second_subject_version
        subject.retest_required = True
        subject.version += 1
        subject.save(update_fields=["current_version", "retest_required", "version", "updated_at"])

    with pytest.raises(DatabaseError), transaction.atomic():
        KeywordSetVersion.objects.create(
            keyword_set=keyword_set,
            user=user,
            subject=subject,
            subject_version=first_subject_version,
            version_no=formal.version_no + 1,
            content_digest="d" * 64,
            item_count=1,
            created_by=user,
        )
