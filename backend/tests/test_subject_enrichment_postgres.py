import hashlib
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.db import DatabaseError, close_old_connections, connection, connections, transaction
from django.test import RequestFactory
from django_redis import get_redis_connection

from apps.admin_rbac.permissions import resolve_admin_context
from apps.plans.services import create_plan, create_plan_version, publish_plan_version
from apps.plans.subscription_services import grant_trial
from apps.quotas.models import QuotaAccount, QuotaHold, QuotaHoldGroup, QuotaLedgerEntry
from apps.subjects.enrichment_services import confirm_enrichment, create_enrichment_job
from apps.subjects.enrichment_tasks import execute_enrichment_task
from apps.subjects.models import (
    Subject,
    SubjectEnrichmentConfirmation,
    SubjectEnrichmentJob,
    SubjectType,
)
from apps.subjects.schema_snapshots import build_schema_snapshot, materialize_defaults
from apps.users.models import User
from apps.web_sources.http_transport import FetchResult
from apps.web_sources.models import WebSourceImport
from apps.web_sources.services import confirm_import, execute_import

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def require_services():
    if connection.vendor != "postgresql":
        pytest.skip("Run via scripts/test-subject-enrichment.* with PostgreSQL/Redis/Celery.")
    call_command("sync_plan_catalog", "--apply", verbosity=0)
    call_command("sync_admin_rbac", "--apply", verbosity=0)
    call_command("sync_subject_catalog", "--apply", verbosity=0)
    redis = get_redis_connection("default")
    assert redis.ping()
    redis.flushdb()
    yield
    redis.flushdb()


def _admin():
    return User.objects.create_superuser(
        phone=f"137{uuid.uuid4().int % 100000000:08d}",
        nickname="Enrichment admin",
        password="Test-2026!",
    )


def _customer():
    return User.objects.create_user(
        phone=f"138{uuid.uuid4().int % 100000000:08d}",
        nickname="Enrichment customer",
        password="Test-2026!",
        account_status=User.AccountStatus.ACTIVE,
    )


def _grant_subscription(actor, user):
    code = f"enrichment-{uuid.uuid4().hex[:10]}"
    plan = create_plan(
        plan_id=uuid.uuid4(),
        actor=actor,
        data={
            "code": code,
            "name": code,
            "description": "AI enrichment test plan",
            "price_display_mode": "fixed",
            "display_price": "0.00",
            "is_trial": True,
            "sort_order": 1,
        },
    )
    version = create_plan_version(
        plan_id=plan.pk,
        actor=actor,
        expected_plan_version=plan.version,
    )
    publish_plan_version(
        version_id=version.pk,
        actor=actor,
        expected_version=version.version,
        confirm_informal_composite=True,
    )
    user.refresh_from_db()
    return grant_trial(
        requester=actor,
        admin_context=resolve_admin_context(actor),
        user_id=user.pk,
        expected_status_version=user.status_version,
        plan_id=plan.pk,
        opening_note="",
        request_id=uuid.uuid4(),
    )


def _subject(user):
    subject_type = SubjectType.objects.get(key="enterprise")
    snapshot, digest = build_schema_snapshot(subject_type)
    values = materialize_defaults(snapshot)
    values["name"] = "PostgreSQL 示例企业"
    return Subject.objects.create(
        user=user,
        subject_type=subject_type,
        status=Subject.Status.DRAFT,
        draft_values=values,
        schema_version=subject_type.schema_version,
        schema_snapshot_format_version=1,
        schema_snapshot=snapshot,
        schema_digest=digest,
    )


def _confirmed_web_source(user, subject):
    row = WebSourceImport.objects.create(
        user=user,
        subject=subject,
        canonical_url="https://example.com/about",
        display_url="https://example.com/about",
        has_query=False,
        hostname_fingerprint="d" * 64,
        idempotency_key_digest=uuid.uuid4().hex * 2,
        request_digest="e" * 64,
        request_id=uuid.uuid4(),
    )
    body = b"<h1>Trusted confirmed web source</h1><p>Public company profile.</p>"
    fetched = FetchResult(
        request_url=row.canonical_url,
        final_url=row.canonical_url,
        status=200,
        content_type="text/html; charset=utf-8",
        body=body,
        response_sha256=hashlib.sha256(body).hexdigest(),
        redirect_count=0,
        peer_ip="93.184.216.34",
    )
    with patch("apps.web_sources.services.fetch_url", return_value=fetched):
        assert execute_import(import_id=row.pk)["status"] == "succeeded"
    row.refresh_from_db()
    machine = row.latest_parsed_version
    row, confirmed, created = confirm_import(
        user_id=user.pk,
        import_id=row.pk,
        expected_version=row.version,
        source_version_id=machine.pk,
        confirmed_text=machine.canonical_text,
        request_id=uuid.uuid4(),
    )
    assert created is True
    return confirmed


def _create_job(user, subject, parsed, key=None):
    request = RequestFactory().post("/", REMOTE_ADDR="127.0.0.1")
    return create_enrichment_job(
        request=request,
        user_id=user.pk,
        subject_id=subject.pk,
        expected_subject_version=subject.version,
        source_refs=[{"source_type": "web", "parsed_version_id": parsed.pk}],
        target_field_keys=["summary"],
        idempotency_key=key or f"subject-enrichment-{uuid.uuid4().hex}",
        request_id=uuid.uuid4(),
    )[0]


def _wait_for_job(job_id, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = SubjectEnrichmentJob.objects.get(pk=job_id)
        if row.status in {"succeeded", "failed"}:
            return row
        time.sleep(0.2)
    raise AssertionError("subject enrichment worker did not finish in time")


def _quota_projection():
    return (
        QuotaAccount.objects.count(),
        QuotaHoldGroup.objects.count(),
        QuotaHold.objects.count(),
        QuotaLedgerEntry.objects.count(),
        tuple(
            QuotaAccount.objects.order_by("id").values_list("id", "available", "frozen", "version")
        ),
    )


def _facts():
    actor = _admin()
    user = _customer()
    _grant_subscription(actor, user)
    subject = _subject(user)
    parsed = _confirmed_web_source(user, subject)
    return user, subject, parsed


def test_real_worker_executes_mock_and_postgres_guards_immutable_suggestions():
    user, subject, parsed = _facts()
    before_quota = _quota_projection()
    job = _create_job(user, subject, parsed)

    execute_enrichment_task.apply_async(args=[str(job.pk)], queue="ai_content")
    job = _wait_for_job(job.pk)

    assert job.status == SubjectEnrichmentJob.Status.SUCCEEDED
    suggestion = job.suggestions.get(field_key="summary")
    assert suggestion.source_links.count() == 1
    assert _quota_projection() == before_quota

    with pytest.raises(DatabaseError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    (
                        "UPDATE subject_enrichment_suggestions "
                        "SET suggested_value = %s::jsonb WHERE id = %s"
                    ),
                    ['"tampered"', suggestion.pk],
                )

    with pytest.raises(DatabaseError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE subject_enrichment_jobs SET model_key = %s WHERE id = %s",
                    ["tampered-model", job.pk],
                )


def test_concurrent_confirmation_creates_one_fact_and_bumps_subject_once():
    user, subject, parsed = _facts()
    job = _create_job(user, subject, parsed)
    execute_enrichment_task.apply_async(args=[str(job.pk)], queue="ai_content")
    job = _wait_for_job(job.pk)
    suggestion = job.suggestions.get(field_key="summary")
    original_version = subject.version
    decisions = [{"suggestion_id": suggestion.pk, "accepted": True}]
    barrier = threading.Barrier(2)

    def operation():
        close_old_connections()
        barrier.wait()
        try:
            current_user = User.objects.get(pk=user.pk)
            result = confirm_enrichment(
                user_id=current_user.pk,
                subject_id=subject.pk,
                job_id=job.pk,
                expected_subject_version=original_version,
                expected_job_version=job.version,
                decisions=decisions,
                request_id=uuid.uuid4(),
            )
            return result[2]
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            future.result(timeout=20) for future in [pool.submit(operation), pool.submit(operation)]
        ]

    subject.refresh_from_db()
    assert sorted(results) == [False, True]
    assert SubjectEnrichmentConfirmation.objects.filter(job=job).count() == 1
    assert subject.version == original_version + 1
    assert subject.draft_values["summary"] == suggestion.suggested_value


def test_concurrent_same_idempotency_key_creates_one_job():
    user, subject, parsed = _facts()
    barrier = threading.Barrier(2)
    key = f"subject-enrichment-concurrent-{uuid.uuid4().hex}"

    def operation():
        close_old_connections()
        barrier.wait()
        try:
            current_user = User.objects.get(pk=user.pk)
            current_subject = Subject.objects.get(pk=subject.pk)
            return _create_job(current_user, current_subject, parsed, key=key).pk
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = [
            future.result(timeout=20) for future in [pool.submit(operation), pool.submit(operation)]
        ]

    assert ids[0] == ids[1]
    assert SubjectEnrichmentJob.objects.filter(user=user, subject=subject).count() == 1
