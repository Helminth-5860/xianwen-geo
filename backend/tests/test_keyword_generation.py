import hashlib
import uuid
from datetime import time, timedelta
from unittest.mock import patch

import pytest
from django.conf import settings
from django.core.management import call_command
from django.db import transaction
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.keywords.generation_exceptions import (
    KeywordGenerationIdempotencyConflict,
    KeywordGenerationInProgress,
    KeywordGenerationLimitExceeded,
    KeywordGenerationProviderUnavailable,
    KeywordGenerationRegenerationConfirmationRequired,
)
from apps.keywords.generation_services import (
    claim_keyword_generation_job,
    create_keyword_generation_job,
    execute_keyword_generation,
)
from apps.keywords.generation_tasks import dispatch_keyword_generation_jobs
from apps.keywords.models import (
    KeywordGenerationEvent,
    KeywordGenerationJob,
    KeywordGenerationResult,
    KeywordSet,
    KeywordSetVersion,
)
from apps.plans.models import Plan, PlanVersion, Subscription
from apps.quotas.catalog import QUOTA_CATALOG
from apps.quotas.models import (
    QuotaAccount,
    QuotaHold,
    QuotaHoldGroup,
    QuotaLedgerEntry,
)
from apps.quotas.services import initialize_subscription_accounts
from apps.subjects.models import (
    Subject,
    SubjectName,
    SubjectType,
    SubjectVersion,
)
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


def _limits(*, regenerations=2, generation_limit=5):
    values = {definition.source_limit_key: 0 for definition in QUOTA_CATALOG}
    values["keyword_regenerations_per_cycle"] = regenerations
    values["keyword_generation_limit"] = generation_limit
    return values


def _facts(*, regenerations=2, generation_limit=5):
    suffix = uuid.uuid4().hex[:10]
    user = User.objects.create_user(
        phone=f"139{uuid.uuid4().int % 100000000:08d}",
        nickname="Keyword generation user",
        password=PASSWORD,
        account_status=User.AccountStatus.ACTIVE,
    )
    subject_type = SubjectType.objects.get(key="enterprise")
    snapshot, digest = build_schema_snapshot(subject_type)
    values = materialize_defaults(snapshot)
    values["name"] = "示例企业"
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
    with transaction.atomic():
        subject_version = SubjectVersion.objects.create(
            subject=subject,
            version_no=1,
            field_values=values,
            schema_version=subject.schema_version,
            schema_snapshot_format_version=1,
            schema_snapshot=snapshot,
            schema_digest=digest,
            field_values_digest=values_digest(values),
            semantic_digest=hashlib.sha256(f"generation-{suffix}".encode()).hexdigest(),
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

    now = timezone.now()
    limits = _limits(
        regenerations=regenerations,
        generation_limit=generation_limit,
    )
    plan = Plan.objects.create(
        code=f"keyword-generation-{suffix}",
        name="Keyword generation plan",
        is_trial=True,
        status=Plan.Status.PUBLISHED,
    )
    plan_version = PlanVersion.objects.create(
        plan=plan,
        version_no=1,
        status=PlanVersion.Status.PUBLISHED,
        valid_days=30,
        queue_priority=1,
        effective_config={"limits": limits},
        config_digest="a" * 64,
        snapshot_generated_at=now,
        published_at=now,
    )
    subscription = Subscription.objects.create(
        user=user,
        source_type=Subscription.SourceType.TRIAL_GRANT,
        plan=plan,
        plan_version=plan_version,
        plan_version_no=1,
        entitlement_snapshot={"limits": limits},
        entitlement_digest="b" * 64,
        starts_at=now - timedelta(days=1),
        ends_at=now + timedelta(days=20),
        cycle_anchor_day=now.day,
        cycle_anchor_time=time(0, 0),
        is_trial=True,
        activated_at=now,
        request_id=uuid.uuid4(),
    )
    initialize_subscription_accounts(
        subscription=subscription,
        request_id=uuid.uuid4(),
    )
    return user, subject, subject_version, subscription


def _create(
    user,
    subject,
    subject_version,
    *,
    expected_version=0,
    regenerate=False,
    key=None,
    target_count=3,
):
    return create_keyword_generation_job(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_subject_version_id=subject_version.pk,
        expected_keyword_set_version=expected_version,
        target_count=target_count,
        include_short=True,
        include_long_tail=True,
        include_regional=False,
        regions=[],
        regenerate=regenerate,
        idempotency_key=key or f"keyword-generation-{uuid.uuid4()}",
        request_id=uuid.uuid4(),
    )


def _subject_account(subject):
    return QuotaAccount.objects.get(
        subject=subject,
        quota_type="keyword_regenerations",
    )


def test_first_generation_is_free_and_applies_complete_draft_only():
    user, subject, subject_version, _ = _facts()
    job, created = _create(user, subject, subject_version)

    assert created is True
    assert job.billing_mode == KeywordGenerationJob.BillingMode.FREE_INITIAL
    assert job.quota_hold_id is None
    assert execute_keyword_generation(job_id=job.pk) == {"status": "succeeded"}

    job.refresh_from_db()
    keyword_set = KeywordSet.objects.get(subject=subject)
    items = list(keyword_set.draft_items.order_by("sort_order"))
    account = _subject_account(subject)

    assert job.status == KeywordGenerationJob.Status.SUCCEEDED
    assert keyword_set.version == 1
    assert len(items) == 3
    assert {item.structure_type for item in items} == {
        "short",
        "long_tail",
    }
    assert all(item.business_category for item in items)
    assert all(item.search_intent for item in items)
    assert all(item.relevance_score is not None for item in items)
    assert all(item.priority for item in items)
    assert all(item.ai_reason for item in items)
    assert KeywordGenerationResult.objects.filter(job=job).count() == 1
    assert KeywordSetVersion.objects.count() == 0
    assert account.available == 2
    assert account.frozen == 0


def test_same_idempotency_key_replays_and_one_active_job_blocks_second():
    user, subject, version, _ = _facts()
    key = "keyword-generation-idempotency-0001"
    first, created = _create(
        user,
        subject,
        version,
        key=key,
    )
    replay, replay_created = _create(
        user,
        subject,
        version,
        key=key,
    )

    assert created is True
    assert replay_created is False
    assert replay.pk == first.pk
    with pytest.raises(KeywordGenerationIdempotencyConflict):
        _create(
            user,
            subject,
            version,
            key=key,
            target_count=2,
        )
    with pytest.raises(KeywordGenerationInProgress):
        _create(user, subject, version)


def test_server_computes_regeneration_and_requires_explicit_confirmation():
    user, subject, version, _ = _facts()
    first, _ = _create(user, subject, version)
    execute_keyword_generation(job_id=first.pk)

    with pytest.raises(KeywordGenerationRegenerationConfirmationRequired):
        _create(
            user,
            subject,
            version,
            expected_version=1,
            regenerate=False,
        )

    second, _ = _create(
        user,
        subject,
        version,
        expected_version=1,
        regenerate=True,
    )
    account = _subject_account(subject)
    group = second.quota_hold

    assert second.billing_mode == KeywordGenerationJob.BillingMode.REGENERATION
    assert group is not None
    assert account.available == 1
    assert account.frozen == 1
    assert group.requested_amount == 1


def test_successful_regeneration_consumes_once_and_retry_call_is_idempotent():
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

    assert execute_keyword_generation(job_id=second.pk)["status"] == "succeeded"
    assert execute_keyword_generation(job_id=second.pk)["status"] == "succeeded"
    second.refresh_from_db()
    second.quota_hold.refresh_from_db()
    account = _subject_account(subject)
    account.refresh_from_db()

    assert second.quota_hold.consumed_amount == 1
    assert second.quota_hold.released_amount == 0
    assert account.available == 1
    assert account.frozen == 0
    assert (
        QuotaLedgerEntry.objects.filter(
            hold__group=second.quota_hold,
            action=QuotaLedgerEntry.Action.CONSUME,
        ).count()
        == 1
    )
    assert KeywordSet.objects.get(subject=subject).version == 2


@override_settings(
    KEYWORD_GENERATION_MOCK_SCENARIO="temporary",
    KEYWORD_GENERATION_MAX_PROVIDER_ATTEMPTS=1,
)
def test_retry_exhaustion_releases_regeneration_hold():
    user, subject, version, _ = _facts()
    with override_settings(KEYWORD_GENERATION_MOCK_SCENARIO="success"):
        first, _ = _create(user, subject, version)
        execute_keyword_generation(job_id=first.pk)
    second, _ = _create(
        user,
        subject,
        version,
        expected_version=1,
        regenerate=True,
    )

    result = execute_keyword_generation(job_id=second.pk)
    second.refresh_from_db()
    second.quota_hold.refresh_from_db()
    account = _subject_account(subject)
    account.refresh_from_db()

    assert result["status"] == "failed"
    assert second.quota_hold.consumed_amount == 0
    assert second.quota_hold.released_amount == 1
    assert account.available == 2
    assert account.frozen == 0


@override_settings(KEYWORD_GENERATION_MOCK_SCENARIO="invalid_response")
def test_invalid_provider_output_releases_regeneration_hold():
    user, subject, version, _ = _facts()
    with override_settings(KEYWORD_GENERATION_MOCK_SCENARIO="success"):
        first, _ = _create(user, subject, version)
        execute_keyword_generation(job_id=first.pk)
    second, _ = _create(
        user,
        subject,
        version,
        expected_version=1,
        regenerate=True,
    )

    assert execute_keyword_generation(job_id=second.pk)["status"] == "failed"
    second.refresh_from_db()
    second.quota_hold.refresh_from_db()
    assert second.stable_error_code == "KEYWORD_GENERATION_INVALID_RESPONSE"
    assert second.quota_hold.released_amount == 1
    assert KeywordSet.objects.get(subject=subject).version == 1


def test_user_draft_change_causes_conflict_and_releases_hold():
    from apps.keywords.services import save_keyword_draft

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
    current = KeywordSet.objects.get(subject=subject)
    save_keyword_draft(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=current.version,
        expected_subject_version_id=version.pk,
        items=[
            {
                "text": "用户并发编辑",
                "structure_type": "general",
                "is_regional": False,
            }
        ],
    )

    assert execute_keyword_generation(job_id=second.pk)["status"] == "conflict"
    second.refresh_from_db()
    second.quota_hold.refresh_from_db()
    account = _subject_account(subject)
    account.refresh_from_db()

    assert second.stable_error_code == "KEYWORD_VERSION_CONFLICT"
    assert second.quota_hold.released_amount == 1
    assert account.available == 2
    assert KeywordSet.objects.get(subject=subject).draft_items.get().text == ("用户并发编辑")


def test_subject_version_change_causes_conflict_and_releases_regeneration_hold():
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
    with transaction.atomic():
        next_version = SubjectVersion.objects.create(
            subject=subject,
            version_no=2,
            field_values=version.field_values,
            schema_version=version.schema_version,
            schema_snapshot_format_version=version.schema_snapshot_format_version,
            schema_snapshot=version.schema_snapshot,
            schema_digest=version.schema_digest,
            field_values_digest=version.field_values_digest,
            semantic_digest=hashlib.sha256(b"generation-subject-v2").hexdigest(),
            official_name=version.official_name,
            created_by=user,
        )
        subject.current_version = next_version
        subject.version += 1
        subject.save(update_fields=["current_version", "version", "updated_at"])

    assert execute_keyword_generation(job_id=second.pk)["status"] == "conflict"
    second.refresh_from_db()
    second.quota_hold.refresh_from_db()
    account = _subject_account(subject)
    account.refresh_from_db()

    assert second.stable_error_code == "KEYWORD_SUBJECT_VERSION_CONFLICT"
    assert second.quota_hold.released_amount == 1
    assert account.available == 2
    assert account.frozen == 0
    assert KeywordSet.objects.get(subject=subject).version == 1


def test_dispatcher_enqueues_each_due_job_without_executing_inline():
    user, subject, version, _ = _facts()
    job, _ = _create(user, subject, version)

    with patch(
        "apps.keywords.generation_tasks.execute_keyword_generation_task.apply_async"
    ) as apply_async:
        result = dispatch_keyword_generation_jobs()

    assert result == {"queued": 1}
    apply_async.assert_called_once()
    assert apply_async.call_args.kwargs["args"] == [str(job.pk)]
    assert apply_async.call_args.kwargs["queue"] == "ai_content"
    assert "request_id" in apply_async.call_args.kwargs["headers"]
    assert "correlation_id" in apply_async.call_args.kwargs["headers"]
    job.refresh_from_db()
    assert job.status == "queued"


def test_stale_worker_generation_cannot_apply_over_new_lease():
    user, subject, version, _ = _facts()
    job, _ = _create(user, subject, version)
    _, old_generation = claim_keyword_generation_job(job_id=job.pk)
    KeywordGenerationJob.objects.filter(pk=job.pk).update(
        started_at=timezone.now()
        - timedelta(seconds=settings.KEYWORD_GENERATION_RUNNING_STALE_SECONDS + 1)
    )
    _, new_generation = claim_keyword_generation_job(job_id=job.pk)

    assert new_generation != old_generation
    assert (
        execute_keyword_generation(
            job_id=job.pk,
            expected_generation=old_generation,
        )["status"]
        == "running"
    )
    assert not KeywordSet.objects.filter(subject=subject).exists()
    assert (
        execute_keyword_generation(
            job_id=job.pk,
            expected_generation=new_generation,
        )["status"]
        == "succeeded"
    )


def test_plan_limit_and_unavailable_provider_fail_before_job_creation():
    user, subject, version, _ = _facts(generation_limit=2)

    with pytest.raises(KeywordGenerationLimitExceeded):
        _create(user, subject, version, target_count=3)
    assert not KeywordGenerationJob.objects.exists()

    with override_settings(KEYWORD_GENERATION_PROVIDER="unavailable"):
        with pytest.raises(KeywordGenerationProviderUnavailable):
            _create(user, subject, version, target_count=2)
    assert not KeywordGenerationJob.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_generation_api_is_strict_async_owner_scoped_and_hides_internal_data():
    user, subject, version, _ = _facts()
    client = APIClient()
    client.force_authenticate(user)
    with patch(
        "apps.keywords.generation_views.execute_keyword_generation_task.apply_async"
    ) as enqueue:
        response = client.post(
            f"/api/v1/subjects/{subject.pk}/keywords/generate",
            {
                "expected_subject_version_id": str(version.pk),
                "expected_keyword_set_version": 0,
                "target_count": 2,
                "include_short": False,
                "include_long_tail": False,
                "include_regional": False,
                "regions": [],
                "regenerate": False,
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY="keyword-generation-api-key-0001",
        )
    assert response.status_code == 202
    assert response["Cache-Control"] == "no-store"
    enqueue.assert_called_once()
    payload = response.json()["data"]
    assert payload["status"] == "queued"
    assert payload["billing"]["billing_mode"] == "free_initial"
    assert "input_digest" not in str(payload)
    assert "output_digest" not in str(payload)
    assert "input_subject_values" not in str(payload)
    assert "historical_exclusions" not in str(payload)

    strict = client.post(
        f"/api/v1/subjects/{subject.pk}/keywords/generate",
        {
            "expected_subject_version_id": str(version.pk),
            "expected_keyword_set_version": 0,
            "target_count": 2,
            "extra": "forged",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="keyword-generation-api-key-0002",
    )
    assert strict.status_code == 422

    outsider = User.objects.create_user(
        phone=f"136{uuid.uuid4().int % 100000000:08d}",
        nickname="Outsider",
        password=PASSWORD,
    )
    outsider_client = APIClient()
    outsider_client.force_authenticate(outsider)
    hidden = outsider_client.get(f"/api/v1/keyword-jobs/{payload['id']}")
    assert hidden.status_code == 404


def test_generated_metadata_and_base_relation_survive_explicit_formal_commit():
    from apps.keywords.services import (
        commit_keyword_version,
        save_keyword_draft,
    )

    user, subject, subject_version, _ = _facts()
    job, _ = _create(user, subject, subject_version)
    execute_keyword_generation(job_id=job.pk)
    keyword_set = KeywordSet.objects.get(subject=subject)
    rows = list(keyword_set.draft_items.order_by("sort_order"))
    payload = [
        {
            "text": row.text,
            "structure_type": row.structure_type,
            "is_regional": row.is_regional,
            "region_level": row.region_level,
            "region_text": row.region_text,
            "base_keyword_text": rows[0].text if index == 1 else None,
            "business_category": "edited-category" if index == 1 else row.business_category,
            "search_intent": row.search_intent,
            "relevance_score": row.relevance_score,
            "priority": "low" if index == 1 else row.priority,
            "ai_reason": row.ai_reason,
        }
        for index, row in enumerate(rows)
    ]
    keyword_set, changed = save_keyword_draft(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=keyword_set.version,
        expected_subject_version_id=subject_version.pk,
        items=payload,
    )
    assert changed is True
    keyword_set, formal = commit_keyword_version(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=keyword_set.version,
        expected_subject_version_id=subject_version.pk,
    )
    formal_rows = list(formal.keywords.order_by("sort_order"))

    assert formal_rows[1].base_keyword_id == formal_rows[0].pk
    assert formal_rows[1].business_category == "edited-category"
    assert formal_rows[1].priority == "low"
    assert formal_rows[1].relevance_score == rows[1].relevance_score
    assert formal_rows[1].ai_reason == rows[1].ai_reason
    assert keyword_set.current_version_id == formal.pk


def test_events_and_result_store_only_validated_safe_evidence():
    user, subject, version, _ = _facts()
    job, _ = _create(user, subject, version)
    execute_keyword_generation(job_id=job.pk)

    result = KeywordGenerationResult.objects.get(job=job)
    events = list(KeywordGenerationEvent.objects.filter(job=job))

    assert result.output_snapshot
    assert result.output_digest
    assert result.provider_metrics == {"mock": True, "item_count": 3}
    assert sorted(event.event_type for event in events) == ["started", "succeeded"]
    serialized = str([event.safe_summary for event in events])
    assert "official_name" not in serialized
    assert "provider" not in serialized
    assert "prompt" not in serialized
    assert QuotaHoldGroup.objects.count() == 0
    assert QuotaHold.objects.count() == 0
