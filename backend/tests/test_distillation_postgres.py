import uuid
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.db import DatabaseError, connection, transaction
from django.test import override_settings
from django.utils import timezone

from apps.keywords.distillation_services import (
    claim_distillation_job,
    confirm_distillation,
    execute_distillation,
)
from apps.keywords.generation_services import execute_keyword_generation
from apps.keywords.models import (
    DistillationEvent,
    DistillationItem,
    DistillationJob,
    DistillationResult,
    DistillationSet,
    DistillationWorkspace,
    KeywordSet,
)
from apps.quotas.services import _create_initialized_account
from apps.users.models import Tenant, User
from tests.test_distillation import _account, _create, _facts
from tests.test_keyword_generation import _create as create_keyword_generation
from tests.test_keyword_generation import _facts as keyword_generation_facts

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="PostgreSQL distillation guards require PostgreSQL.",
    ),
]


@pytest.fixture(autouse=True)
def seed_subject_catalog():
    call_command("sync_subject_catalog", "--apply", verbosity=0)


def _succeeded():
    user, subject, _, subscription, _, version = _facts()
    job, _ = _create(user, subject, version)
    assert execute_distillation(job_id=job.pk)["status"] == "succeeded"
    workspace = DistillationWorkspace.objects.get(subject=subject)
    return user, subject, subscription, version, job, workspace


def test_database_allows_only_one_active_distillation_per_subject():
    user, subject, _, subscription, _, version = _facts()
    first, _ = _create(user, subject, version)
    with pytest.raises(DatabaseError), transaction.atomic():
        DistillationJob.objects.create(
            user=user,
            subject=subject,
            subject_version=version.subject_version,
            input_keyword_set_version=version,
            subscription=subscription,
            status=DistillationJob.Status.QUEUED,
            billing_mode=DistillationJob.BillingMode.FREE_INITIAL,
            expected_workspace_version=0,
            input_subject_values={"official_name": version.subject_version.official_name},
            input_keywords=[{"id": str(version.keywords.first().pk)}],
            provider_key="mock",
            model_key="mock-keyword-distillation-v1",
            adapter_version="1",
            prompt_version="keyword-distillation-v1",
            input_digest="a" * 64,
            idempotency_key_digest="b" * 64,
            request_digest="c" * 64,
        )
    assert DistillationJob.objects.get(pk=first.pk).status == "queued"


def test_same_tenant_operator_can_distill_subject_owned_by_teammate():
    tenant_suffix = uuid.uuid4().hex[:8]
    tenant = Tenant.objects.create(
        key=f"tenant-{tenant_suffix}",
        display_name=f"Tenant {tenant_suffix}",
    )
    owner = User.objects.create_user(
        phone=f"139{uuid.uuid4().int % 100000000:08d}",
        nickname="Subject owner",
        password="Correct-Horse-Battery-2026!",
        account_status=User.AccountStatus.ACTIVE,
        tenant=tenant,
    )
    operator = User.objects.create_user(
        phone=f"139{uuid.uuid4().int % 100000000:08d}",
        nickname="Tenant operator",
        password="Correct-Horse-Battery-2026!",
        account_status=User.AccountStatus.ACTIVE,
        tenant=tenant,
    )
    operator, subject, subject_version, _ = keyword_generation_facts(
        user=operator,
        subject_owner=owner,
        tenant=tenant,
    )
    generation, _ = create_keyword_generation(operator, subject, subject_version)
    assert execute_keyword_generation(job_id=generation.pk)["status"] == "succeeded"
    keyword_version = KeywordSet.objects.get(subject=subject).current_version

    distillation, _ = _create(operator, subject, keyword_version)
    assert execute_distillation(job_id=distillation.pk)["status"] == "succeeded"
    workspace = DistillationWorkspace.objects.get(subject=subject)
    workspace, confirmed = confirm_distillation(
        user_id=operator.pk,
        subject_id=subject.pk,
        expected_version=workspace.version,
    )

    assert workspace.current_set_id == confirmed.pk
    assert confirmed.user_id == operator.pk


@override_settings(DISTILLATION_MOCK_SCENARIO="invalid_response")
def test_free_initial_provider_failure_terminalizes_without_quota_hold_record():
    user, subject, _, _, _, version = _facts()
    job, _ = _create(user, subject, version)

    assert job.billing_mode == DistillationJob.BillingMode.FREE_INITIAL
    assert job.quota_hold_id is None
    assert execute_distillation(job_id=job.pk) == {
        "status": "failed",
        "code": "DISTILLATION_INVALID_RESPONSE",
    }

    job.refresh_from_db()
    assert job.status == DistillationJob.Status.FAILED
    assert job.stable_error_code == "DISTILLATION_INVALID_RESPONSE"


def test_job_result_event_and_confirmed_history_are_database_immutable():
    user, subject, _, _, job, workspace = _succeeded()
    result = DistillationResult.objects.get(job=job)
    event = DistillationEvent.objects.filter(job=job).first()
    workspace, version = confirm_distillation(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=workspace.version,
    )
    item = version.items.first()

    statements = [
        ("UPDATE distillation_jobs SET input_digest = %s WHERE id = %s", ["f" * 64, job.pk]),
        (
            "UPDATE distillation_results SET output_digest = %s WHERE id = %s",
            ["e" * 64, result.pk],
        ),
        ("DELETE FROM distillation_events WHERE id = %s", [event.pk]),
        ("UPDATE distillation_sets SET content_digest = %s WHERE id = %s", ["d" * 64, version.pk]),
        ("UPDATE distillation_items SET user_reason = %s WHERE id = %s", ["forged", item.pk]),
    ]
    for sql, params in statements:
        with pytest.raises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
    assert DistillationSet.objects.get(pk=version.pk).content_digest == version.content_digest
    assert DistillationItem.objects.get(pk=item.pk).user_reason == item.user_reason
    assert workspace.current_set_id == version.pk


def test_draft_rejects_canonical_keyword_from_another_formal_version():
    _, _, _, version, _, workspace = _succeeded()
    other_user, _, _, _, _, other_version = _facts()
    foreign_keyword = other_version.keywords.first()
    merge_item = workspace.draft_items.filter(action="merge").first()

    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE distillation_draft_items SET canonical_keyword_id = %s WHERE id = %s",
                [foreign_keyword.pk, merge_item.pk],
            )
    merge_item.refresh_from_db()
    assert merge_item.canonical_keyword.keyword_set_version_id == version.pk
    assert foreign_keyword.keyword_set_version.user_id == other_user.pk


def test_deferred_guard_rejects_single_member_merge_group():
    user, subject, _, version, job, workspace = _succeeded()
    result = DistillationResult.objects.get(job=job)
    keyword = version.keywords.first()
    with pytest.raises(DatabaseError), transaction.atomic():
        forged = DistillationSet.objects.create(
            workspace=workspace,
            user=user,
            subject=subject,
            subject_version=version.subject_version,
            input_keyword_set_version=version,
            source_result=result,
            version_no=1,
            content_digest="a" * 64,
            item_count=1,
            confirmed_by=user,
            confirmed_at=timezone.now(),
        )
        DistillationItem.objects.create(
            distillation_set=forged,
            source_keyword=keyword,
            action="merge",
            canonical_keyword=keyword,
            merge_group_key=uuid.uuid4(),
            ai_action="keep",
            ai_reason="validated evidence",
            sort_order=0,
        )
    assert not DistillationSet.objects.filter(content_digest="a" * 64).exists()


def test_regeneration_settles_original_hold_across_cycle_boundary():
    user, subject, subscription, version, _, workspace = _succeeded()
    second, _ = _create(
        user,
        subject,
        version,
        workspace_version=workspace.version,
        regenerate=True,
    )
    original = _account(subject)
    with transaction.atomic():
        later = _create_initialized_account(
            subscription=subscription,
            subject=subject,
            quota_type="distillation_regenerations",
            amount=2,
            cycle_started_at=original.cycle_started_at + timedelta(days=1),
            cycle_ends_at=original.cycle_ends_at,
            request_id=uuid.uuid4(),
            actor=None,
        )

    assert execute_distillation(job_id=second.pk)["status"] == "succeeded"
    original.refresh_from_db()
    later.refresh_from_db()
    second.quota_hold.refresh_from_db()
    assert second.quota_hold.consumed_amount == 1
    assert original.available == 1 and original.frozen == 0
    assert later.available == 2 and later.frozen == 0


def test_new_formal_keyword_version_can_replace_workspace_input_atomically():
    from apps.keywords.services import commit_keyword_version, save_keyword_draft

    user, subject, _, first_version, _, workspace = _succeeded()
    keyword_set = first_version.keyword_set
    items = [
        {
            "text": keyword.text,
            "structure_type": keyword.structure_type,
            "is_regional": keyword.is_regional,
            "region_level": keyword.region_level,
            "region_text": keyword.region_text,
        }
        for keyword in first_version.keywords.order_by("sort_order")
    ]
    items.append({"text": "新增正式关键词", "structure_type": "general", "is_regional": False})
    keyword_set, changed = save_keyword_draft(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=keyword_set.version,
        expected_subject_version_id=first_version.subject_version_id,
        items=items,
    )
    assert changed is True
    keyword_set, second_version = commit_keyword_version(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=keyword_set.version,
        expected_subject_version_id=first_version.subject_version_id,
    )
    job, _ = _create(
        user,
        subject,
        second_version,
        workspace_version=workspace.version,
        regenerate=True,
    )

    assert execute_distillation(job_id=job.pk)["status"] == "succeeded"
    workspace.refresh_from_db()
    assert workspace.draft_input_version_id == second_version.pk
    assert workspace.draft_source_result.job_id == job.pk
    assert workspace.version == 2
    assert workspace.draft_items.count() == second_version.item_count
    assert not workspace.draft_items.filter(
        source_keyword__keyword_set_version=first_version
    ).exists()


def test_terminal_transition_requires_matching_exactly_once_settlement():
    user, subject, _, version, _, workspace = _succeeded()
    second, _ = _create(
        user,
        subject,
        version,
        workspace_version=workspace.version,
        regenerate=True,
    )
    claim_distillation_job(job_id=second.pk)
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE distillation_jobs SET status = 'failed', finished_at = %s, "
                "stable_error_code = 'FORGED', version = version + 1 WHERE id = %s",
                [timezone.now(), second.pk],
            )
    second.refresh_from_db()
    second.quota_hold.refresh_from_db()
    assert second.status == "running"
    assert second.quota_hold.status == "open"
