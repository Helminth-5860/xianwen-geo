import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.db import (
    DatabaseError,
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django_redis import get_redis_connection
from rest_framework.test import APIClient

from apps.admin_rbac.permissions import resolve_admin_context
from apps.plans.change_services import (
    SubscriptionSubjectLimitReconciliationRequired,
    cancel_scheduled_change,
    preview_subscription_change,
)
from apps.plans.lifecycle import (
    SUBJECT_LIMIT_RECONCILIATION_REQUIRED,
    execute_due_renewal,
)
from apps.plans.models import Plan, Subscription, SubscriptionChange
from apps.plans.services import (
    create_plan,
    create_plan_version,
    publish_plan_version,
    update_plan_version,
)
from apps.plans.subscription_services import grant_trial
from apps.subjects.models import (
    Subject,
    SubjectContext,
    SubjectEvent,
    SubjectType,
    SubjectVersion,
)
from apps.subjects.schema_snapshots import build_schema_snapshot, materialize_defaults
from apps.subjects.subject_services import (
    SubjectLimitReached,
    activate_subject,
    archive_subject,
    create_subject,
    effective_subject_activation_limit,
)
from apps.subjects.version_services import commit_subject_version
from apps.users.models import User
from tests.subject_risk_helpers import install_empty_published_risk_catalog
from tests.test_plan_changes import admin, customer
from tests.test_plan_changes_postgres import cancel_digests, change_operation
from tests.test_subscriptions_postgres import activate, make_application

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def require_postgres_and_redis():
    if connection.vendor != "postgresql":
        pytest.skip("Run through scripts/test-subject-schema.* with PostgreSQL and Redis.")
    call_command("sync_subject_catalog", "--apply", verbosity=0)
    call_command("sync_plan_catalog", "--apply", verbosity=0)
    install_empty_published_risk_catalog()
    call_command("sync_admin_rbac", "--apply", verbosity=0)
    redis = get_redis_connection("default")
    assert redis.ping()
    redis.flushdb()
    yield
    redis.flushdb()


def make_user(phone=None):
    return User.objects.create_user(
        phone=phone or f"138{uuid.uuid4().int % 100000000:08d}",
        nickname="Subject PostgreSQL user",
        password="Correct-Horse-Battery-2026!",
    )


def make_subject(user, subject_type, *, status=Subject.Status.DRAFT, values=None):
    snapshot, digest = build_schema_snapshot(subject_type)
    draft_values = materialize_defaults(snapshot)
    draft_values.update(values or {})
    return Subject.objects.create(
        user=user,
        subject_type=subject_type,
        status=status,
        draft_values=draft_values,
        schema_version=subject_type.schema_version,
        schema_snapshot_format_version=1,
        schema_snapshot=snapshot,
        schema_digest=digest,
    )


def parallel(*operations):
    barrier = threading.Barrier(len(operations))

    def run(operation):
        close_old_connections()
        barrier.wait()
        try:
            return operation()
        except Exception as exc:
            return exc
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=len(operations)) as pool:
        futures = [pool.submit(run, operation) for operation in operations]
        return [future.result(timeout=30) for future in futures]


def test_subject_data_postgresql_guards_are_installed():
    expected = {
        "subjects_subject_guard",
        "subjects_version_guard",
        "subjects_event_guard",
        "subjects_context_guard",
        "subjects_context_consistency",
        "subjects_context_subject_consistency",
    }
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgname = ANY(%s)",
            [list(expected)],
        )
        installed = {row[0] for row in cursor.fetchall()}
    assert installed == expected


def test_create_has_frozen_snapshot_and_reserves_first_version_number():
    user = make_user()
    subject_type = SubjectType.objects.get(key="enterprise")
    subject = create_subject(
        user_id=user.pk,
        subject_type_id=subject_type.pk,
        expected_schema_version=subject_type.schema_version,
        initial_values={"name": "Frozen"},
        request_id=uuid.uuid4(),
    )
    assert subject.schema_snapshot_format_version == 1
    assert not SubjectVersion.objects.filter(subject=subject).exists()
    assert not hasattr(subject, "latest_version")
    assert SubjectVersion._meta.get_field("version_no").null is False


def test_subject_version_event_context_and_subject_reject_raw_delete():
    user = make_user()
    subject_type = SubjectType.objects.get(key="enterprise")
    subject = make_subject(user, subject_type, values={"name": "Guarded subject"})
    context = SubjectContext.objects.create(user=user, current_subject=subject)
    event = SubjectEvent.objects.create(
        subject=subject,
        event_type=SubjectEvent.EventType.CREATED,
        from_status="",
        to_status=subject.status,
        actor=user,
        request_id=uuid.uuid4(),
    )
    subject, version = commit_subject_version(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=subject.version,
        product_confirmations=[],
        request_id=uuid.uuid4(),
    )
    for table, row_id in (
        ("subject_versions", version.pk),
        ("subject_events", event.pk),
        ("subject_contexts", context.pk),
        ("subjects", subject.pk),
    ):
        with pytest.raises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(f"DELETE FROM {table} WHERE id=%s", [row_id])


def test_raw_sql_rejects_snapshot_mutation_archived_edit_and_illegal_status():
    user = make_user()
    subject_type = SubjectType.objects.get(key="enterprise")
    subject = make_subject(user, subject_type)

    immutable_updates = (
        ("schema_version", subject.schema_version + 1),
        ("schema_digest", "f" * 64),
        ("schema_snapshot_format_version", 2),
        ("user_id", make_user().pk),
    )
    for column, value in immutable_updates:
        with pytest.raises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(f"UPDATE subjects SET {column}=%s WHERE id=%s", [value, subject.pk])

    archive_subject(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=subject.version,
        request_id=uuid.uuid4(),
    )
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE subjects SET draft_values=%s::jsonb, version=version+1 WHERE id=%s",
                ['{"name":"tampered"}', subject.pk],
            )
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE subjects SET status='draft', version=version+1 WHERE id=%s",
                [subject.pk],
            )


def test_context_deferred_guard_rejects_cross_user_and_archived_reference():
    owner = make_user()
    other = make_user()
    subject_type = SubjectType.objects.get(key="enterprise")
    subject = make_subject(owner, subject_type)

    with pytest.raises(DatabaseError), transaction.atomic():
        SubjectContext.objects.create(user=other, current_subject=subject)
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

    context = SubjectContext.objects.create(user=owner, current_subject=subject)
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE subjects SET status='archived', version=version+1 WHERE id=%s",
                [subject.pk],
            )
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    context.refresh_from_db()
    assert context.current_subject_id == subject.pk


def test_no_plan_concurrent_second_draft_allows_exactly_one():
    user = make_user()
    subject_type = SubjectType.objects.get(key="enterprise")
    payload = {
        "subject_type_id": str(subject_type.pk),
        "expected_schema_version": subject_type.schema_version,
        "initial_values": {},
    }

    def create_one(index):
        thread_user = User.objects.get(pk=user.pk)
        client = APIClient()
        client.force_authenticate(thread_user)
        response = client.post(
            "/api/v1/subjects",
            {**payload, "initial_values": {"name": f"Draft {index}"}},
            format="json",
        )
        if response.status_code == 201:
            return "created"
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "SUBJECT_LIMIT_REACHED"
        return "limited"

    results = parallel(lambda: create_one(1), lambda: create_one(2))
    assert sorted(results) == ["created", "limited"]
    assert Subject.objects.filter(user=user, status=Subject.Status.DRAFT).count() == 1


def test_valid_subscription_does_not_limit_draft_count():
    actor = admin()
    user = customer("13800138107")
    open_formal(actor, user, limit=1)
    subject_type = SubjectType.objects.get(key="enterprise")

    first = create_subject(
        user_id=user.pk,
        subject_type_id=subject_type.pk,
        expected_schema_version=subject_type.schema_version,
        initial_values={"name": "First draft"},
        request_id=uuid.uuid4(),
    )
    second = create_subject(
        user_id=user.pk,
        subject_type_id=subject_type.pk,
        expected_schema_version=subject_type.schema_version,
        initial_values={"name": "Second draft"},
        request_id=uuid.uuid4(),
    )

    assert first.pk != second.pk
    assert Subject.objects.filter(user=user, status=Subject.Status.DRAFT).count() == 2


def test_active_limit_concurrent_last_slot_allows_exactly_one():
    user = make_user()
    subject_type = SubjectType.objects.get(key="enterprise")
    subjects = [make_subject(user, subject_type), make_subject(user, subject_type)]

    def activate_one(subject):
        close_old_connections()
        try:
            activate_subject(
                user_id=user.pk,
                subject_id=subject.pk,
                expected_version=subject.version,
                request_id=uuid.uuid4(),
            )
            return "active"
        except SubjectLimitReached:
            return "limited"
        finally:
            close_old_connections()

    with (
        patch(
            "apps.subjects.subject_services._effective_subscription_locked",
            return_value=object(),
        ),
        patch("apps.subjects.subject_services.effective_subject_activation_limit", return_value=1),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        results = list(pool.map(activate_one, subjects))
    assert sorted(results) == ["active", "limited"]
    assert Subject.objects.filter(user=user, status=Subject.Status.ACTIVE).count() == 1


def test_archive_current_clears_context_in_same_transaction_and_failure_rolls_back():
    user = make_user()
    subject_type = SubjectType.objects.get(key="enterprise")
    subject = create_subject(
        user_id=user.pk,
        subject_type_id=subject_type.pk,
        expected_schema_version=subject_type.schema_version,
        initial_values={},
        request_id=uuid.uuid4(),
    )
    archived = archive_subject(
        user_id=user.pk,
        subject_id=subject.pk,
        expected_version=subject.version,
        request_id=uuid.uuid4(),
    )
    assert archived.status == Subject.Status.ARCHIVED
    assert SubjectContext.objects.get(user=user).current_subject is None

    second = create_subject(
        user_id=user.pk,
        subject_type_id=subject_type.pk,
        expected_schema_version=subject_type.schema_version,
        initial_values={},
        request_id=uuid.uuid4(),
    )
    before = (second.status, second.version, SubjectEvent.objects.filter(subject=second).count())
    with patch("apps.subjects.subject_services._subject_event", side_effect=RuntimeError("event")):
        with pytest.raises(RuntimeError, match="event"):
            archive_subject(
                user_id=user.pk,
                subject_id=second.pk,
                expected_version=second.version,
                request_id=uuid.uuid4(),
            )
    second.refresh_from_db()
    assert (
        second.status,
        second.version,
        SubjectEvent.objects.filter(subject=second).count(),
    ) == before


def test_subject_context_update_requires_version_and_same_current_is_noop():
    user = make_user()
    subject_type = SubjectType.objects.get(key="enterprise")
    subject = make_subject(user, subject_type)
    context = SubjectContext.objects.create(user=user, current_subject=subject)

    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE subject_contexts SET current_subject_id=NULL WHERE id=%s",
                [context.pk],
            )
    context.refresh_from_db()
    assert context.current_subject_id == subject.pk


def test_redis_is_not_subject_or_limit_fact_source():
    redis = get_redis_connection("default")
    redis.set("xw0202:subject-limit", "999999", ex=30)
    redis.flushdb()
    assert Subject.objects.count() == 0
    assert SubjectContext.objects.count() == 0


def _plan_limit_value(item):
    if item.value_type == "integer":
        return item.integer_value
    if item.value_type == "boolean":
        return item.boolean_value
    if item.value_type in {"text", "enum"}:
        return item.text_value
    return None if item.json_value == {"value": None} else item.json_value


def published_limit_plan(actor, *, limit, trial=False, plan=None):
    if plan is None:
        plan = create_plan(
            plan_id=uuid.uuid4(),
            actor=actor,
            data={
                "code": f"subject-limit-{uuid.uuid4().hex[:12]}",
                "name": "Subject limit integration plan",
                "description": "Subject limit integration plan",
                "price_display_mode": "fixed",
                "display_price": "0.00" if trial else "99.00",
                "is_trial": trial,
                "sort_order": 1,
            },
        )
    else:
        plan = Plan.objects.get(pk=plan.pk)
    version = create_plan_version(
        plan_id=plan.pk,
        actor=actor,
        expected_plan_version=plan.version,
    )
    limits = [
        {
            "key": item.limit_key,
            "value": limit if item.limit_key == "subject_active_limit" else _plan_limit_value(item),
        }
        for item in version.limits.all()
    ]
    version = update_plan_version(
        version_id=version.pk,
        actor=actor,
        expected_version=version.version,
        valid_days=version.valid_days,
        queue_priority=version.queue_priority,
        limits=limits,
        model_permissions=[
            {
                "model_key": item.model_key,
                "sort_order": item.sort_order,
                "selected_by_default": item.selected_by_default,
            }
            for item in version.model_permissions.all()
        ],
    )
    version = publish_plan_version(
        version_id=version.pk,
        actor=actor,
        expected_version=version.version,
        confirm_informal_composite=True,
    )
    plan.refresh_from_db()
    return plan, version


def active_subjects(user, count):
    subject_type = SubjectType.objects.get(key="enterprise")
    return [
        make_subject(user, subject_type, status=Subject.Status.ACTIVE) for _index in range(count)
    ]


def open_formal(actor, user, *, limit):
    plan, version = published_limit_plan(actor, limit=limit)
    application = make_application(user, plan, version)
    subscription, _application, _metadata = activate(actor, application)
    return subscription, plan, version


def test_subscription_and_trial_creation_recheck_target_subject_limit():
    actor = admin()
    formal_user = customer("13800138101")
    active_subjects(formal_user, 2)
    formal_plan, formal_version = published_limit_plan(actor, limit=1)
    application = make_application(formal_user, formal_plan, formal_version)
    with pytest.raises(SubscriptionSubjectLimitReconciliationRequired):
        activate(actor, application)
    assert not Subscription.objects.filter(user=formal_user).exists()

    trial_user = customer("13800138102")
    active_subjects(trial_user, 2)
    trial_plan, _trial_version = published_limit_plan(actor, limit=1, trial=True)
    with pytest.raises(SubscriptionSubjectLimitReconciliationRequired):
        grant_trial(
            requester=actor,
            admin_context=resolve_admin_context(actor),
            user_id=trial_user.pk,
            expected_status_version=trial_user.status_version,
            plan_id=trial_plan.pk,
            opening_note="",
            request_id=uuid.uuid4(),
        )
    assert not Subscription.objects.filter(user=trial_user).exists()


def test_immediate_plan_change_preview_and_execution_recheck_target_limit():
    actor = admin()
    user = customer("13800138103")
    source, _source_plan, _source_version = open_formal(actor, user, limit=3)
    active_subjects(user, 2)
    target_plan, target_version = published_limit_plan(actor, limit=1)
    preview = preview_subscription_change(
        source=source,
        target_version=target_version,
        requested_type=SubscriptionChange.ChangeType.DOWNGRADE,
        quota_policy=SubscriptionChange.QuotaPolicy.OVERWRITE,
    )
    assert preview.active_count == 2
    assert preview.target_limit == 1
    assert preview.required_archive_count == 1
    with pytest.raises(SubscriptionSubjectLimitReconciliationRequired):
        change_operation(
            actor.pk,
            source.pk,
            target_plan.pk,
            target_version.pk,
            "subject-limit-immediate-change-0001",
            change_type="downgrade",
        )
    source.refresh_from_db()
    assert source.status == Subscription.Status.ACTIVE
    assert not SubscriptionChange.objects.filter(from_subscription=source).exists()


def test_scheduled_renewal_future_cap_blocks_activation_and_cancel_restores_current_cap():
    actor = admin()
    user = customer("13800138104")
    source, plan, _source_version = open_formal(actor, user, limit=10)
    existing = active_subjects(user, 5)
    subject_type = SubjectType.objects.get(key="enterprise")
    draft = make_subject(user, subject_type)
    _plan, target_version = published_limit_plan(actor, limit=5, plan=plan)
    change = change_operation(
        actor.pk,
        source.pk,
        plan.pk,
        target_version.pk,
        "subject-limit-renewal-cap-0001",
        policy="retain",
        change_type="renewal",
    )
    assert change.status == SubscriptionChange.Status.SCHEDULED
    source.refresh_from_db()
    assert effective_subject_activation_limit(user=user, subscription=source) == 5
    with pytest.raises(SubjectLimitReached):
        activate_subject(
            user_id=user.pk,
            subject_id=draft.pk,
            expected_version=draft.version,
            request_id=uuid.uuid4(),
        )
    assert Subject.objects.filter(user=user, status=Subject.Status.ACTIVE).count() == len(existing)

    reason = "Cancel scheduled renewal"
    cancelled = cancel_scheduled_change(
        requester=actor,
        admin_context=resolve_admin_context(actor),
        change_id=change.pk,
        expected_version=change.version,
        reason=reason,
        digests=cancel_digests(actor, change, "subject-renewal-cancel-cap-0001", reason),
        request_id=uuid.uuid4(),
    )
    assert cancelled.status == SubscriptionChange.Status.CANCELLED
    assert effective_subject_activation_limit(user=user, subscription=source) == 10
    activated = activate_subject(
        user_id=user.pk,
        subject_id=draft.pk,
        expected_version=draft.version,
        request_id=uuid.uuid4(),
    )
    assert activated.status == Subject.Status.ACTIVE
    assert Subject.objects.filter(user=user, status=Subject.Status.ACTIVE).count() == 6


def test_subject_activation_and_scheduled_renewal_cancel_race_is_safe():
    actor = admin()
    user = customer("13800138108")
    source, plan, _source_version = open_formal(actor, user, limit=10)
    active_subjects(user, 5)
    subject_type = SubjectType.objects.get(key="enterprise")
    draft = make_subject(user, subject_type)
    _plan, target_version = published_limit_plan(actor, limit=5, plan=plan)
    change = change_operation(
        actor.pk,
        source.pk,
        plan.pk,
        target_version.pk,
        "subject-limit-renewal-cancel-race-0001",
        policy="retain",
        change_type="renewal",
    )
    reason = "Cancel scheduled renewal during activation"

    results = parallel(
        lambda: cancel_scheduled_change(
            requester=User.objects.get(pk=actor.pk),
            admin_context=resolve_admin_context(User.objects.get(pk=actor.pk)),
            change_id=change.pk,
            expected_version=change.version,
            reason=reason,
            digests=cancel_digests(
                actor,
                change,
                "subject-renewal-cancel-race-key-0001",
                reason,
            ),
            request_id=uuid.uuid4(),
        ),
        lambda: activate_subject(
            user_id=user.pk,
            subject_id=draft.pk,
            expected_version=draft.version,
            request_id=uuid.uuid4(),
        ),
    )

    cancelled = [result for result in results if isinstance(result, SubscriptionChange)]
    activation = [result for result in results if not isinstance(result, SubscriptionChange)]
    assert len(cancelled) == len(activation) == 1
    assert cancelled[0].status == SubscriptionChange.Status.CANCELLED
    assert isinstance(activation[0], (Subject, SubjectLimitReached))
    change.refresh_from_db()
    source.refresh_from_db()
    assert change.status == SubscriptionChange.Status.CANCELLED
    assert effective_subject_activation_limit(user=user, subscription=source) == 10
    assert Subject.objects.filter(user=user, status=Subject.Status.ACTIVE).count() in {5, 6}


def test_scheduled_renewal_and_subject_activation_race_is_serialized():
    actor = admin()
    user = customer("13800138106")
    source, plan, _source_version = open_formal(actor, user, limit=10)
    active_subjects(user, 5)
    subject_type = SubjectType.objects.get(key="enterprise")
    draft = make_subject(user, subject_type)
    _plan, target_version = published_limit_plan(actor, limit=5, plan=plan)

    results = parallel(
        lambda: change_operation(
            actor.pk,
            source.pk,
            plan.pk,
            target_version.pk,
            "subject-limit-renewal-race-0001",
            policy="retain",
            change_type="renewal",
        ),
        lambda: activate_subject(
            user_id=user.pk,
            subject_id=draft.pk,
            expected_version=draft.version,
            request_id=uuid.uuid4(),
        ),
    )

    changes = [result for result in results if isinstance(result, SubscriptionChange)]
    activation_results = [
        result for result in results if not isinstance(result, SubscriptionChange)
    ]
    assert len(changes) == 1
    assert changes[0].status == SubscriptionChange.Status.SCHEDULED
    assert len(activation_results) == 1
    assert isinstance(activation_results[0], (Subject, SubjectLimitReached))

    source.refresh_from_db()
    draft.refresh_from_db()
    active_count = Subject.objects.filter(
        user=user,
        status=Subject.Status.ACTIVE,
    ).count()
    assert effective_subject_activation_limit(user=user, subscription=source) == 5
    assert active_count in {5, 6}

    execute_due_renewal(
        change_id=changes[0].pk,
        request_id=uuid.uuid4(),
        now=source.ends_at + timedelta(seconds=1),
    )
    change = SubscriptionChange.objects.get(pk=changes[0].pk)
    target = Subscription.objects.filter(source_change=change).first()
    if active_count > 5:
        assert change.status == SubscriptionChange.Status.SCHEDULED
        assert change.stable_error_code == SUBJECT_LIMIT_RECONCILIATION_REQUIRED
        assert target is None
    else:
        assert change.status == SubscriptionChange.Status.EXECUTED
        assert target is not None
        assert target.status == Subscription.Status.ACTIVE
        assert active_count <= 5


def test_scheduled_renewal_subject_reconciliation_is_recoverable():
    actor = admin()
    user = customer("13800138105")
    source, plan, _source_version = open_formal(actor, user, limit=3)
    subjects = active_subjects(user, 2)
    _plan, target_version = published_limit_plan(actor, limit=1, plan=plan)
    change = change_operation(
        actor.pk,
        source.pk,
        plan.pk,
        target_version.pk,
        "subject-limit-renewal-retry-0001",
        policy="retain",
        change_type="renewal",
    )
    execute_due_renewal(
        change_id=change.pk,
        request_id=uuid.uuid4(),
        now=source.ends_at + timedelta(seconds=1),
    )
    source.refresh_from_db()
    change.refresh_from_db()
    assert source.status == Subscription.Status.EXPIRED
    assert change.status == SubscriptionChange.Status.SCHEDULED
    assert change.stable_error_code == SUBJECT_LIMIT_RECONCILIATION_REQUIRED
    assert change.next_attempt_at is not None
    assert not hasattr(change, "target_subscription")

    archived = archive_subject(
        user_id=user.pk,
        subject_id=subjects[0].pk,
        expected_version=subjects[0].version,
        request_id=uuid.uuid4(),
    )
    assert archived.status == Subject.Status.ARCHIVED
    execute_due_renewal(
        change_id=change.pk,
        request_id=uuid.uuid4(),
        now=change.next_attempt_at + timedelta(seconds=1),
    )
    change.refresh_from_db()
    assert change.status == SubscriptionChange.Status.EXECUTED
    assert change.target_subscription.status == Subscription.Status.ACTIVE
