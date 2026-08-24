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

from apps.keywords.distillation_exceptions import (
    DistillationIdempotencyConflict,
    DistillationInProgress,
    DistillationProviderUnavailable,
    DistillationRegenerationConfirmationRequired,
    DistillationValuesInvalid,
    DistillationVersionConflict,
    DistillationVersionNoChanges,
)
from apps.keywords.distillation_services import (
    claim_distillation_job,
    confirm_distillation,
    create_distillation_job,
    execute_distillation,
    save_distillation_draft,
)
from apps.keywords.distillation_tasks import dispatch_distillation_jobs
from apps.keywords.models import (
    DistillationEvent,
    DistillationItem,
    DistillationJob,
    DistillationResult,
    DistillationSet,
    DistillationWorkspace,
)
from apps.keywords.services import commit_keyword_version, save_keyword_draft
from apps.plans.models import Plan, PlanVersion, Subscription
from apps.quotas.catalog import QUOTA_CATALOG
from apps.quotas.models import QuotaAccount, QuotaLedgerEntry
from apps.quotas.services import initialize_subscription_accounts
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


def _limits(
    *,
    distillation_regenerations=2,
    question_limit=0,
    question_regenerations=0,
):
    values = {definition.source_limit_key: 0 for definition in QUOTA_CATALOG}
    values["distillation_regenerations_per_cycle"] = distillation_regenerations
    values["keyword_generation_limit"] = 10
    values["question_bank_limit"] = question_limit
    values["question_bank_regenerations_per_cycle"] = question_regenerations
    return values


def _facts(
    *,
    distillation_regenerations=2,
    question_limit=0,
    question_regenerations=0,
    model_permissions=None,
):
    suffix = uuid.uuid4().hex[:10]
    user = User.objects.create_user(
        phone=f"139{uuid.uuid4().int % 100000000:08d}",
        nickname="Distillation user",
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
            semantic_digest=hashlib.sha256(f"distillation-{suffix}".encode()).hexdigest(),
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
        subject.status = Subject.Status.ACTIVE
        subject.version += 1
        subject.save(update_fields=["current_version", "status", "version", "updated_at"])

    now = timezone.now()
    limits = _limits(
        distillation_regenerations=distillation_regenerations,
        question_limit=question_limit,
        question_regenerations=question_regenerations,
    )
    entitlement = {"limits": limits}
    if model_permissions is not None:
        entitlement["model_permissions"] = [dict(item) for item in model_permissions]

    plan = Plan.objects.create(
        code=f"distillation-{suffix}",
        name="Distillation plan",
        is_trial=True,
        status=Plan.Status.PUBLISHED,
    )
    plan_version = PlanVersion.objects.create(
        plan=plan,
        version_no=1,
        status=PlanVersion.Status.PUBLISHED,
        valid_days=30,
        queue_priority=1,
        effective_config=entitlement,
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
        entitlement_snapshot=entitlement,
        entitlement_digest="b" * 64,
        starts_at=now - timedelta(days=1),
        ends_at=now + timedelta(days=20),
        cycle_anchor_day=now.day,
        cycle_anchor_time=time(0, 0),
        is_trial=True,
        activated_at=now,
        request_id=uuid.uuid4(),
    )
    initialize_subscription_accounts(subscription=subscription, request_id=uuid.uuid4())
    keyword_set, _ = save_keyword_draft(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=0,
        expected_subject_version_id=subject_version.pk,
        items=[
            {"text": "品牌咨询", "structure_type": "short", "is_regional": False},
            {"text": "企业品牌服务", "structure_type": "long_tail", "is_regional": False},
            {"text": "品牌企业服务", "structure_type": "long_tail", "is_regional": False},
            {"text": "无关旧词", "structure_type": "general", "is_regional": False},
            {"text": "低价值宽泛词", "structure_type": "general", "is_regional": False},
        ],
    )
    keyword_set, keyword_version = commit_keyword_version(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=keyword_set.version,
        expected_subject_version_id=subject_version.pk,
    )
    return user, subject, subject_version, subscription, keyword_set, keyword_version


def _create(user, subject, version, *, workspace_version=0, regenerate=False, key=None):
    return create_distillation_job(
        user_id=user.pk,
        subject_id=subject.pk,
        keyword_set_version_id=version.pk,
        expected_workspace_version=workspace_version,
        regenerate=regenerate,
        idempotency_key=key or f"distillation-{uuid.uuid4()}",
        request_id=uuid.uuid4(),
    )


def _account(subject):
    return QuotaAccount.objects.get(subject=subject, quota_type="distillation_regenerations")


def _draft_request(workspace):
    return [
        {
            "source_keyword_id": str(item.source_keyword_id),
            "action": item.action,
            "canonical_keyword_id": (
                str(item.canonical_keyword_id) if item.canonical_keyword_id else None
            ),
            "merge_group_key": str(item.merge_group_key) if item.merge_group_key else None,
            "user_reason": item.user_reason,
        }
        for item in workspace.draft_items.order_by("sort_order", "id")
    ]


def test_initial_distillation_is_free_and_preserves_all_four_actions():
    user, subject, _, _, _, keyword_version = _facts()
    before = list(keyword_version.keywords.values_list("id", "text"))
    job, created = _create(user, subject, keyword_version)

    assert created is True
    assert job.billing_mode == DistillationJob.BillingMode.FREE_INITIAL
    assert job.quota_hold_id is None
    assert execute_distillation(job_id=job.pk) == {"status": "succeeded"}

    job.refresh_from_db()
    workspace = DistillationWorkspace.objects.get(subject=subject)
    rows = list(workspace.draft_items.order_by("sort_order"))
    assert [row.action for row in rows] == ["keep", "merge", "merge", "delete", "low_value"]
    assert rows[1].merge_group_key == rows[2].merge_group_key
    assert rows[1].canonical_keyword_id == rows[2].canonical_keyword_id
    assert rows[1].canonical_keyword_id in {rows[1].source_keyword_id, rows[2].source_keyword_id}
    assert all(row.ai_reason for row in rows)
    assert workspace.version == 1
    assert DistillationResult.objects.filter(job=job).count() == 1
    assert list(keyword_version.keywords.values_list("id", "text")) == before
    assert not QuotaAccount.objects.filter(
        subject=subject, quota_type="distillation_regenerations"
    ).exists()


def test_idempotency_one_active_and_regeneration_quota_exactly_once():
    user, subject, _, _, _, version = _facts()
    key = "distillation-idempotency-0001"
    first, created = _create(user, subject, version, key=key)
    replay, replay_created = _create(user, subject, version, key=key)
    assert created is True and replay_created is False and replay.pk == first.pk
    with pytest.raises(DistillationIdempotencyConflict):
        _create(user, subject, version, key=key, regenerate=True)
    with pytest.raises(DistillationInProgress):
        _create(user, subject, version)

    execute_distillation(job_id=first.pk)
    workspace = DistillationWorkspace.objects.get(subject=subject)
    with pytest.raises(DistillationRegenerationConfirmationRequired):
        _create(user, subject, version, workspace_version=workspace.version)
    second, _ = _create(
        user,
        subject,
        version,
        workspace_version=workspace.version,
        regenerate=True,
    )
    assert second.quota_hold_id is not None
    assert execute_distillation(job_id=second.pk) == {"status": "succeeded"}
    assert execute_distillation(job_id=second.pk) == {"status": "succeeded"}
    second.quota_hold.refresh_from_db()
    account = _account(subject)
    assert second.quota_hold.consumed_amount == 1
    assert second.quota_hold.released_amount == 0
    assert account.available == 1 and account.frozen == 0
    assert (
        QuotaLedgerEntry.objects.filter(
            hold__group=second.quota_hold,
            action=QuotaLedgerEntry.Action.CONSUME,
        ).count()
        == 1
    )


@override_settings(DISTILLATION_MOCK_SCENARIO="temporary", DISTILLATION_MAX_PROVIDER_ATTEMPTS=1)
def test_retry_exhaustion_releases_regeneration_hold():
    user, subject, _, _, _, version = _facts()
    with override_settings(DISTILLATION_MOCK_SCENARIO="success"):
        first, _ = _create(user, subject, version)
        execute_distillation(job_id=first.pk)
    workspace = DistillationWorkspace.objects.get(subject=subject)
    second, _ = _create(
        user, subject, version, workspace_version=workspace.version, regenerate=True
    )
    assert execute_distillation(job_id=second.pk)["status"] == "failed"
    second.refresh_from_db()
    second.quota_hold.refresh_from_db()
    account = _account(subject)
    assert second.quota_hold.released_amount == 1
    assert account.available == 2 and account.frozen == 0


@override_settings(DISTILLATION_MOCK_SCENARIO="invalid_response")
def test_invalid_provider_response_is_fail_closed_and_releases_hold():
    user, subject, _, _, _, version = _facts()
    with override_settings(DISTILLATION_MOCK_SCENARIO="success"):
        first, _ = _create(user, subject, version)
        execute_distillation(job_id=first.pk)
    workspace = DistillationWorkspace.objects.get(subject=subject)
    second, _ = _create(
        user, subject, version, workspace_version=workspace.version, regenerate=True
    )
    assert execute_distillation(job_id=second.pk)["status"] == "failed"
    second.refresh_from_db()
    assert second.stable_error_code == "DISTILLATION_INVALID_RESPONSE"
    assert second.quota_hold.released_amount == 1


def test_user_adjustment_preserves_ai_provenance_and_confirmation_is_immutable():
    user, subject, _, _, _, version = _facts()
    job, _ = _create(user, subject, version)
    execute_distillation(job_id=job.pk)
    workspace = DistillationWorkspace.objects.get(subject=subject)
    original = list(DistillationResult.objects.get(job=job).output_snapshot)
    items = _draft_request(workspace)
    delete_item = next(item for item in items if item["action"] == "delete")
    delete_item.update(
        action="keep",
        canonical_keyword_id=None,
        merge_group_key=None,
        user_reason="业务确认后保留",
    )
    workspace, changed = save_distillation_draft(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=workspace.version,
        items=items,
    )
    assert changed is True and workspace.version == 2
    adjusted = workspace.draft_items.get(source_keyword_id=delete_item["source_keyword_id"])
    assert adjusted.action == "keep"
    assert adjusted.ai_action == "delete"
    assert adjusted.ai_reason
    assert adjusted.user_reason == "业务确认后保留"
    assert adjusted.user_overridden is True
    assert DistillationResult.objects.get(job=job).output_snapshot == original

    workspace, formal = confirm_distillation(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=workspace.version,
    )
    assert formal.version_no == 1 and formal.item_count == 5
    assert (
        formal.items.get(source_keyword_id=delete_item["source_keyword_id"]).ai_action == "delete"
    )
    assert workspace.current_set_id == formal.pk
    with pytest.raises(DistillationVersionNoChanges):
        confirm_distillation(
            user_id=user.pk,
            subject_id=subject.pk,
            expected_version=workspace.version,
        )
    with pytest.raises(TypeError):
        formal.save()
    with pytest.raises(TypeError):
        formal.items.first().save()


def test_invalid_cross_region_merge_and_optimistic_concurrency_are_rejected():
    user, subject, _, _, keyword_set, version = _facts()
    job, _ = _create(user, subject, version)
    execute_distillation(job_id=job.pk)
    workspace = DistillationWorkspace.objects.get(subject=subject)
    with pytest.raises(DistillationVersionConflict):
        save_distillation_draft(
            user_id=user.pk,
            subject_id=subject.pk,
            expected_version=workspace.version + 1,
            items=_draft_request(workspace),
        )

    rows = list(version.keywords.order_by("sort_order"))
    rows[0].is_regional = True
    rows[0].region_level = "city"
    rows[0].region_text = "上海市"
    rows[0].region_matching_key = "上海市"
    rows[0].save = lambda *args, **kwargs: None
    inputs = list(job.input_keywords)
    inputs[0]["is_regional"] = True
    inputs[0]["region_level"] = "city"
    inputs[0]["region_text"] = "上海市"
    inputs[0]["region_matching_key"] = "上海市"
    job.input_keywords = inputs
    job.save = lambda *args, **kwargs: None
    items = _draft_request(workspace)
    group = uuid.uuid4()
    items[0].update(
        action="merge",
        canonical_keyword_id=items[1]["source_keyword_id"],
        merge_group_key=str(group),
    )
    items[1].update(
        action="merge",
        canonical_keyword_id=items[1]["source_keyword_id"],
        merge_group_key=str(group),
    )
    with patch("apps.keywords.distillation_services._keyword_snapshot", return_value=inputs):
        with pytest.raises(DistillationValuesInvalid):
            save_distillation_draft(
                user_id=user.pk,
                subject_id=subject.pk,
                expected_version=workspace.version,
                items=items,
            )
    keyword_set.refresh_from_db()


def test_dispatcher_and_late_worker_lease_are_safe():
    user, subject, _, _, _, version = _facts()
    job, _ = _create(user, subject, version)
    with patch("apps.keywords.distillation_tasks.execute_distillation_task.apply_async") as enqueue:
        assert dispatch_distillation_jobs() == {"queued": 1}
    enqueue.assert_called_once()
    assert enqueue.call_args.kwargs["queue"] == "ai_content"

    _, old_generation = claim_distillation_job(job_id=job.pk)
    DistillationJob.objects.filter(pk=job.pk).update(
        started_at=timezone.now()
        - timedelta(seconds=settings.DISTILLATION_RUNNING_STALE_SECONDS + 1)
    )
    _, new_generation = claim_distillation_job(job_id=job.pk)
    assert new_generation != old_generation
    assert execute_distillation(job_id=job.pk, expected_generation=old_generation)["status"] == (
        "running"
    )
    assert not DistillationWorkspace.objects.filter(subject=subject).exists()
    assert execute_distillation(job_id=job.pk, expected_generation=new_generation)["status"] == (
        "succeeded"
    )


def test_unavailable_provider_fails_before_job_or_quota_hold():
    user, subject, _, _, _, version = _facts()
    with override_settings(DISTILLATION_PROVIDER="unavailable"):
        with pytest.raises(DistillationProviderUnavailable):
            _create(user, subject, version)
    assert not DistillationJob.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_distillation_api_async_draft_confirm_owner_scope_and_safe_payloads():
    user, subject, _, _, _, version = _facts()
    client = APIClient()
    client.force_authenticate(user)
    with patch("apps.keywords.distillation_views.execute_distillation_task.apply_async") as enqueue:
        response = client.post(
            f"/api/v1/subjects/{subject.pk}/distillations",
            {
                "keyword_set_version_id": str(version.pk),
                "expected_workspace_version": 0,
                "regenerate": False,
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY="distillation-api-key-0001",
        )
    assert response.status_code == 202 and response["Cache-Control"] == "no-store"
    enqueue.assert_called_once()
    job_id = response.json()["data"]["id"]
    assert "input_keywords" not in str(response.json()["data"])
    assert "input_subject_values" not in str(response.json()["data"])
    execute_distillation(job_id=job_id)

    draft = client.get(f"/api/v1/subjects/{subject.pk}/distillations/draft")
    draft_data = draft.json()["data"]
    assert draft.status_code == 200 and len(draft_data["items"]) == 5
    payload = _draft_request(DistillationWorkspace.objects.get(subject=subject))
    saved = client.patch(
        f"/api/v1/subjects/{subject.pk}/distillations/draft",
        {"expected_version": draft_data["version"], "items": payload},
        format="json",
    )
    assert saved.status_code == 200
    confirmed = client.post(
        f"/api/v1/subjects/{subject.pk}/distillations/confirm",
        {"expected_version": saved.json()["data"]["version"]},
        format="json",
    )
    assert confirmed.status_code == 201
    current = client.get(f"/api/v1/subjects/{subject.pk}/distillations/current")
    assert current.status_code == 200 and current.json()["data"]["version_no"] == 1

    outsider = User.objects.create_user(
        phone=f"136{uuid.uuid4().int % 100000000:08d}",
        nickname="Outsider",
        password=PASSWORD,
    )
    outsider_client = APIClient()
    outsider_client.force_authenticate(outsider)
    assert outsider_client.get(f"/api/v1/distillation-jobs/{job_id}").status_code == 404
    assert (
        outsider_client.get(f"/api/v1/subjects/{subject.pk}/distillations/draft").status_code == 404
    )


def test_events_and_results_contain_only_validated_safe_evidence():
    user, subject, _, _, _, version = _facts()
    job, _ = _create(user, subject, version)
    execute_distillation(job_id=job.pk)
    result = DistillationResult.objects.get(job=job)
    events = list(DistillationEvent.objects.filter(job=job))
    assert result.provider_metrics == {"mock": True, "item_count": 5}
    assert sorted(event.event_type for event in events) == ["started", "succeeded"]
    serialized = str([event.safe_summary for event in events])
    assert "official_name" not in serialized
    assert "prompt" not in serialized
    assert "api_key" not in serialized
    assert DistillationSet.objects.count() == 0
    assert DistillationItem.objects.count() == 0
