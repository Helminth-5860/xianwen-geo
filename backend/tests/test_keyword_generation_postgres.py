import uuid
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from apps.keywords.generation_services import (
    claim_keyword_generation_job,
    execute_keyword_generation,
)
from apps.keywords.models import (
    Keyword,
    KeywordGenerationEvent,
    KeywordGenerationJob,
    KeywordGenerationResult,
    KeywordSet,
    KeywordSetVersion,
)
from apps.quotas.services import _create_initialized_account
from apps.users.models import Tenant, User
from tests.test_keyword_generation import _create, _facts, _subject_account

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="PostgreSQL keyword generation guards require PostgreSQL.",
    ),
]


@pytest.fixture(autouse=True)
def seed_subject_catalog():
    call_command("sync_subject_catalog", "--apply", verbosity=0)


def test_database_allows_only_one_active_generation_per_subject():
    user, subject, version, subscription = _facts()
    first, _ = _create(user, subject, version)
    with pytest.raises(DatabaseError), transaction.atomic():
        KeywordGenerationJob.objects.create(
            user=user,
            subject=subject,
            subject_version=version,
            subscription=subscription,
            status=KeywordGenerationJob.Status.QUEUED,
            billing_mode=KeywordGenerationJob.BillingMode.FREE_INITIAL,
            expected_keyword_set_version=0,
            target_count=1,
            input_subject_values={"official_name": version.official_name},
            provider_key="mock",
            model_key="mock-keyword-generation-v1",
            adapter_version="1",
            prompt_version="keyword-generation-v1",
            input_digest="a" * 64,
            idempotency_key_digest="b" * 64,
            request_digest="c" * 64,
        )
    assert KeywordGenerationJob.objects.get(pk=first.pk).status == "queued"


def test_tenant_member_can_generate_for_the_shared_subject_with_own_subscription():
    tenant = Tenant.objects.create(key=f"tenant-{uuid.uuid4().hex}", display_name="共享工作区")
    owner = User.objects.create_user(
        phone=f"136{uuid.uuid4().int % 100000000:08d}",
        nickname="主体资料维护人",
        password="Correct-Horse-Battery-2026!",
        account_status=User.AccountStatus.ACTIVE,
        tenant=tenant,
    )
    operator = User.objects.create_user(
        phone=f"135{uuid.uuid4().int % 100000000:08d}",
        nickname="工作区操作人",
        password="Correct-Horse-Battery-2026!",
        account_status=User.AccountStatus.ACTIVE,
        tenant=tenant,
    )
    user, subject, version, _ = _facts(
        user=operator,
        subject_owner=owner,
        tenant=tenant,
    )

    job, created = _create(user, subject, version)

    assert created is True
    assert job.user == operator
    assert job.subject.user == owner
    assert job.subscription.user == operator
    assert execute_keyword_generation(job_id=job.pk) == {"status": "succeeded"}

    keyword_set = KeywordSet.objects.get(subject=subject)
    keyword_set.refresh_from_db()
    assert keyword_set.user == operator
    assert keyword_set.current_version.user == operator
    assert keyword_set.current_version.created_by == operator


def test_keyword_set_guard_rejects_user_from_another_tenant():
    subject_tenant = Tenant.objects.create(
        key=f"tenant-{uuid.uuid4().hex}", display_name="主体工作区"
    )
    other_tenant = Tenant.objects.create(
        key=f"tenant-{uuid.uuid4().hex}", display_name="其他工作区"
    )
    owner = User.objects.create_user(
        phone=f"134{uuid.uuid4().int % 100000000:08d}",
        nickname="主体负责人",
        password="Correct-Horse-Battery-2026!",
        account_status=User.AccountStatus.ACTIVE,
        tenant=subject_tenant,
    )
    outsider = User.objects.create_user(
        phone=f"133{uuid.uuid4().int % 100000000:08d}",
        nickname="其他工作区成员",
        password="Correct-Horse-Battery-2026!",
        account_status=User.AccountStatus.ACTIVE,
        tenant=other_tenant,
    )
    _, subject, version, _ = _facts(
        user=owner,
        subject_owner=owner,
        tenant=subject_tenant,
    )

    with pytest.raises(DatabaseError), transaction.atomic():
        KeywordSet.objects.create(
            user=outsider,
            subject=subject,
            draft_subject_version=version,
            version=1,
        )


def test_job_frozen_facts_and_result_event_evidence_are_database_immutable():
    user, subject, version, _ = _facts()
    job, _ = _create(user, subject, version)
    execute_keyword_generation(job_id=job.pk)
    result = KeywordGenerationResult.objects.get(job=job)
    event = KeywordGenerationEvent.objects.filter(job=job).first()

    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE keyword_generation_jobs SET input_digest = %s WHERE id = %s",
                ["f" * 64, job.pk],
            )
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE keyword_generation_results SET output_digest = %s WHERE id = %s",
                ["e" * 64, result.pk],
            )
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM keyword_generation_events WHERE id = %s",
                [event.pk],
            )


def test_cross_version_base_keyword_is_rejected_by_deferred_guard():
    user, subject, subject_version, _ = _facts()
    first_job, _ = _create(user, subject, subject_version)
    execute_keyword_generation(job_id=first_job.pk)
    keyword_set = KeywordSet.objects.get(subject=subject)
    from apps.keywords.services import commit_keyword_version

    keyword_set, first_version = commit_keyword_version(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=keyword_set.version,
        expected_subject_version_id=subject_version.pk,
    )
    historical_keyword = first_version.keywords.first()

    with pytest.raises(DatabaseError), transaction.atomic():
        second_version = KeywordSetVersion.objects.create(
            keyword_set=keyword_set,
            user=user,
            subject=subject,
            subject_version=subject_version,
            version_no=first_version.version_no + 1,
            content_digest="d" * 64,
            item_count=1,
            created_by=user,
        )
        Keyword.objects.create(
            keyword_set_version=second_version,
            base_keyword=historical_keyword,
            text="invalid cross-version base",
            matching_text="invalid cross-version base",
            structure_type="general",
            is_regional=False,
            region_level="",
            region_text="",
            region_matching_key="",
            sort_order=0,
        )
        keyword_set.current_version = second_version
        keyword_set.version += 1
        keyword_set.save(update_fields=["current_version", "version", "updated_at"])


def test_regeneration_settles_original_hold_when_new_subject_cycle_exists():
    user, subject, version, subscription = _facts(regenerations=2)
    first, _ = _create(user, subject, version)
    execute_keyword_generation(job_id=first.pk)
    second, _ = _create(
        user,
        subject,
        version,
        expected_version=1,
        regenerate=True,
    )
    original = _subject_account(subject)
    with transaction.atomic():
        later = _create_initialized_account(
            subscription=subscription,
            subject=subject,
            quota_type="keyword_regenerations",
            amount=2,
            cycle_started_at=original.cycle_started_at + timedelta(days=1),
            cycle_ends_at=original.cycle_ends_at,
            request_id=uuid.uuid4(),
            actor=None,
        )

    assert execute_keyword_generation(job_id=second.pk)["status"] == "succeeded"
    original.refresh_from_db()
    later.refresh_from_db()
    second.quota_hold.refresh_from_db()

    assert second.quota_hold.consumed_amount == 1
    assert original.available == 1
    assert original.frozen == 0
    assert later.available == 2
    assert later.frozen == 0


def test_subject_cycle_quota_binding_is_database_immutable():
    user, subject, version, _ = _facts()
    _create(user, subject, version)
    account = _subject_account(subject)
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE quota_accounts SET subject_id = NULL WHERE id = %s",
                [account.pk],
            )


def test_terminal_job_requires_matching_exactly_once_settlement():
    user, subject, version, _ = _facts()
    first, _ = _create(user, subject, version)
    execute_keyword_generation(job_id=first.pk)
    second, _ = _create(
        user,
        subject,
        version,
        expected_version=1,
        regenerate=True,
    )
    claim_keyword_generation_job(job_id=second.pk)
    now = timezone.now()
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE keyword_generation_jobs "
                "SET status = 'failed', finished_at = %s, "
                "stable_error_code = 'FORGED', version = version + 1 "
                "WHERE id = %s",
                [now, second.pk],
            )
    second.refresh_from_db()
    assert second.status == "running"
    assert second.quota_hold.status == "open"
