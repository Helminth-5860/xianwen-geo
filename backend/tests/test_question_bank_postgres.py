import uuid

import pytest
from django.core.management import call_command
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from apps.keywords.distillation_services import confirm_distillation, execute_distillation
from apps.keywords.models import DistillationWorkspace
from apps.questions.bank_models import (
    QuestionBankWorkspace,
    QuestionGenerationResult,
)
from apps.questions.catalog import BUILTIN_QUESTION_CATEGORIES
from apps.questions.generation_services import (
    claim_question_generation_job,
    confirm_question_bank,
    execute_question_generation,
    remove_current_question_bank_items,
)
from apps.questions.models import QuestionCategory
from tests.test_distillation import _create as create_distillation
from tests.test_question_bank import create_job, draft_payload, facts

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def require_postgresql():
    if connection.vendor != "postgresql":
        pytest.skip("Dedicated PostgreSQL evidence")
    call_command("sync_subject_catalog", "--apply", verbosity=0)
    for item in BUILTIN_QUESTION_CATEGORIES:
        QuestionCategory.objects.get_or_create(
            key=item.key,
            defaults={
                "name": item.name,
                "normalized_name": item.name.casefold(),
                "description": item.description,
                "generation_guidance": item.generation_guidance,
                "sort_order": item.sort_order,
                "is_builtin": True,
            },
        )


def succeeded():
    user, subject, _, subscription, distilled = facts()
    job, _ = create_job(user, subject, distilled)
    assert execute_question_generation(job_id=job.pk)["status"] == "succeeded"
    workspace = QuestionBankWorkspace.objects.get(subject=subject)
    return user, subject, subscription, distilled, job, workspace


def test_generation_result_and_formal_history_are_database_immutable():
    user, subject, _, _, job, workspace = succeeded()
    result = QuestionGenerationResult.objects.get(job=job)
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE question_generation_results SET item_count = item_count + 1 WHERE id = %s",
                [result.pk],
            )
    _, version = confirm_question_bank(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=workspace.version,
    )
    question = version.questions.first()
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE questions SET text = 'forged history' WHERE id = %s",
                [question.pk],
            )


def test_terminal_transition_requires_exactly_once_hold_settlement():
    _, subject, _, distilled, _, workspace = succeeded()
    user = subject.user
    second, _ = create_job(user, subject, distilled, version=workspace.version, regenerate=True)
    claim_question_generation_job(job_id=second.pk)
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE question_generation_jobs SET status = 'failed', finished_at = %s, "
                "stable_error_code = 'FORGED', version = version + 1 WHERE id = %s",
                [timezone.now(), second.pk],
            )
    second.refresh_from_db()
    second.quota_hold.refresh_from_db()
    assert second.status == "running" and second.quota_hold.status == "open"


def test_regeneration_settles_the_original_lifetime_item_hold():
    user, subject, _, distilled, _, workspace = succeeded()
    second, _ = create_job(user, subject, distilled, version=workspace.version, regenerate=True)
    original = second.quota_hold.allocations.get().account
    available_while_frozen = original.available
    assert original.cycle_started_at is None
    assert original.cycle_ends_at is None
    assert execute_question_generation(job_id=second.pk)["status"] == "succeeded"
    original.refresh_from_db()
    second.quota_hold.refresh_from_db()
    assert second.quota_hold.consumed_amount == 0
    assert second.quota_hold.released_amount == second.question_limit
    assert original.frozen == 0
    assert original.available == available_while_frozen + second.question_limit


def test_generation_hold_uses_item_quota_and_matches_question_limit():
    user, subject, _, _, distilled = facts(limit=2)
    job, _ = create_job(user, subject, distilled)

    job.quota_hold.refresh_from_db()
    assert job.quota_hold.quota_type == "question_generated_items"
    assert job.quota_hold.requested_amount == job.question_limit == 2
    assert execute_question_generation(job_id=job.pk)["status"] == "succeeded"
    job.quota_hold.refresh_from_db()
    assert (
        job.quota_hold.consumed_amount + job.quota_hold.released_amount
        == job.question_limit
    )


def test_workspace_current_version_must_point_to_latest_formal_version():
    user, subject, _, _, _, workspace = succeeded()
    workspace, first = confirm_question_bank(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=workspace.version,
    )
    payload = draft_payload(workspace)
    payload[0]["priority"] = "low" if payload[0]["priority"] != "low" else "high"
    from apps.questions.generation_services import save_question_bank_draft

    workspace, _ = save_question_bank_draft(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=workspace.version,
        items=payload,
    )
    workspace, second = confirm_question_bank(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=workspace.version,
    )
    assert second.version_no == first.version_no + 1
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE question_bank_workspaces SET current_version_id = %s, "
                "version = version + 1 WHERE id = %s",
                [first.pk, workspace.pk],
            )


def test_bulk_remove_old_formal_version_restores_newer_draft_binding():
    user, subject, _, first_distilled, _, workspace = succeeded()
    workspace, first_formal = confirm_question_bank(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=workspace.version,
    )
    distillation_workspace = DistillationWorkspace.objects.get(subject=subject)
    second_distillation_job, _ = create_distillation(
        user,
        subject,
        first_distilled.input_keyword_set_version,
        workspace_version=distillation_workspace.version,
        regenerate=True,
    )
    assert execute_distillation(job_id=second_distillation_job.pk)["status"] == "succeeded"
    distillation_workspace.refresh_from_db()
    _, second_distilled = confirm_distillation(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=distillation_workspace.version,
    )
    workspace.refresh_from_db()
    second_job, _ = create_job(
        user,
        subject,
        second_distilled,
        version=workspace.version,
        regenerate=True,
    )
    assert execute_question_generation(job_id=second_job.pk)["status"] == "succeeded"
    workspace.refresh_from_db()
    newer_draft_ids = list(
        workspace.draft_items.order_by("sort_order").values_list("id", flat=True)
    )
    newer_source_result_id = workspace.draft_source_result_id
    removed_id = first_formal.questions.order_by("sort_order").first().pk

    workspace, second_formal, removed_count = remove_current_question_bank_items(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version_id=first_formal.pk,
        question_ids=[removed_id],
    )

    assert removed_count == 1 and second_formal is not None
    assert second_formal.distillation_set_id == first_formal.distillation_set_id
    assert workspace.draft_distillation_set_id == second_distilled.pk
    assert workspace.draft_source_result_id == newer_source_result_id
    assert list(workspace.draft_items.order_by("sort_order").values_list("id", flat=True)) == (
        newer_draft_ids
    )
