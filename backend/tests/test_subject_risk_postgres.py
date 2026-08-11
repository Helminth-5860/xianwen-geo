import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.db import DatabaseError, close_old_connections, connection, connections, transaction
from django_redis import get_redis_connection

from apps.admin_rbac.models import (
    AdminPermission,
    AdminRole,
    AdminRolePermission,
    CustomerAssignment,
)
from apps.admin_rbac.permissions import resolve_admin_context
from apps.admin_rbac.services import create_admin, create_role
from apps.subjects.models import (
    Subject,
    SubjectReview,
    SubjectReviewEvent,
    SubjectRiskAssessment,
    SubjectRiskCatalogRevision,
    SubjectRiskCatalogState,
    SubjectRiskType,
)
from apps.subjects.risk_engine import catalog_digest
from apps.subjects.risk_services import (
    SubjectReviewStateConflict,
    SubjectReviewVersionConflict,
    capabilities_for_subject,
    decide_review,
    scoped_reviews,
)
from apps.subjects.version_services import commit_subject_version
from apps.users.models import Notification, User
from tests.test_subject_risk import (
    PASSWORD,
    admin_client,
    create_and_commit_flagged_subject,
    payload,
    publish_matching_catalog,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def require_postgres_and_redis():
    if connection.vendor != "postgresql":
        pytest.skip("Run through scripts/test-subject-schema.* with PostgreSQL and Redis.")
    call_command("sync_admin_rbac", "--apply", verbosity=0)
    call_command("sync_subject_catalog", "--apply", verbosity=0)
    SubjectRiskCatalogState.objects.get_or_create(pk=1, defaults={"version": 1})
    redis = get_redis_connection("default")
    assert redis.ping()
    redis.flushdb()
    yield
    redis.flushdb()


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


def force_constraints():
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


def test_subject_risk_guards_and_publish_approval_are_database_enforced():
    _, _, revision = publish_matching_catalog()
    _, _, subject_data = create_and_commit_flagged_subject()
    review = SubjectReview.objects.get(subject_id=subject_data["id"])
    assessment = review.assessment
    hit = assessment.hits.get()
    event = review.events.get(event_type=SubjectReviewEvent.EventType.REQUESTED)
    expected_triggers = {
        "subjects_risk_revision_guard",
        "subjects_risk_assessment_guard",
        "subjects_risk_hit_guard",
        "subjects_review_event_guard",
        "subjects_risk_type_guard",
        "subjects_risk_rule_guard",
        "subjects_review_guard",
        "subjects_risk_assessment_binding",
        "subjects_review_binding",
        "subjects_catalog_revision_approval",
    }
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgname = ANY(%s)",
            [list(expected_triggers)],
        )
        assert {row[0] for row in cursor.fetchall()} == expected_triggers

    statements = [
        (
            "UPDATE subject_risk_catalog_revisions SET snapshot_digest=%s WHERE id=%s",
            ["f" * 64, revision.id],
        ),
        ("UPDATE subject_risk_assessments SET outcome='clear' WHERE id=%s", [assessment.id]),
        ("DELETE FROM subject_risk_hits WHERE id=%s", [hit.id]),
        ("DELETE FROM subject_review_events WHERE id=%s", [event.id]),
        (
            "DELETE FROM subject_risk_types WHERE id=%s",
            [SubjectRiskType.objects.get(key="test.review_required").id],
        ),
    ]
    for sql, params in statements:
        with pytest.raises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(sql, params)

    invalid_snapshot = {"format_version": 1, "risk_types": [], "rules": []}
    with pytest.raises(DatabaseError), transaction.atomic():
        SubjectRiskCatalogRevision.objects.create(
            revision_no=2,
            snapshot=invalid_snapshot,
            snapshot_digest=catalog_digest(invalid_snapshot),
            published_by=None,
            approval_request=None,
        )
        force_constraints()


def test_review_binding_terminal_state_and_concurrent_decision_are_exactly_once():
    _, approver, _ = publish_matching_catalog()
    _, _, subject_data = create_and_commit_flagged_subject()
    review = SubjectReview.objects.get(subject_id=subject_data["id"])
    context = resolve_admin_context(approver)

    def approve():
        request = SimpleNamespace(
            user=approver,
            admin_context=context,
            request_id=str(uuid.uuid4()),
            META={"REMOTE_ADDR": "127.0.0.1", "HTTP_USER_AGENT": "pytest"},
        )
        return decide_review(
            request=request,
            review_id=review.id,
            decision=SubjectReview.Status.APPROVED,
            expected_version=1,
            reason="",
        ).status

    results = parallel(approve, approve)
    assert results.count(SubjectReview.Status.APPROVED) == 1
    assert (
        sum(
            isinstance(item, (SubjectReviewStateConflict, SubjectReviewVersionConflict))
            for item in results
        )
        == 1
    )
    review.refresh_from_db()
    assert review.status == SubjectReview.Status.APPROVED
    assert review.events.filter(event_type=SubjectReviewEvent.EventType.APPROVED).count() == 1
    assert (
        Notification.objects.filter(
            recipient=review.subject.user,
            notification_type=Notification.NotificationType.SUBJECT_REVIEW_APPROVED,
        ).count()
        == 1
    )

    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE subject_reviews SET status='pending', version=version+1 WHERE id=%s",
                [review.id],
            )


def test_new_version_and_review_decision_race_never_authorizes_stale_version():
    _, approver, _ = publish_matching_catalog()
    owner, client, subject_data = create_and_commit_flagged_subject()
    subject = Subject.objects.get(pk=subject_data["id"])
    old_review = SubjectReview.objects.get(subject=subject)
    updated = client.patch(
        f"/api/v1/subjects/{subject.id}/draft",
        {"expected_version": subject.version, "values": {"name": "Flagged concurrent"}},
        format="json",
    )
    expected_version = payload(updated)["version"]
    context = resolve_admin_context(approver)

    def commit():
        return commit_subject_version(
            user_id=owner.id,
            subject_id=subject.id,
            expected_version=expected_version,
            product_confirmations=[],
            request_id=uuid.uuid4(),
        )[1].version_no

    def approve():
        request = SimpleNamespace(
            user=approver,
            admin_context=context,
            request_id=str(uuid.uuid4()),
            META={"REMOTE_ADDR": "127.0.0.1", "HTTP_USER_AGENT": "pytest"},
        )
        return decide_review(
            request=request,
            review_id=old_review.id,
            decision=SubjectReview.Status.APPROVED,
            expected_version=old_review.version,
            reason="",
        ).status

    results = parallel(commit, approve)
    assert 2 in results
    old_review.refresh_from_db()
    subject.refresh_from_db()
    assert subject.current_version.version_no == 2
    assert old_review.status in {SubjectReview.Status.APPROVED, SubjectReview.Status.SUPERSEDED}
    assert (
        SubjectReview.objects.filter(
            subject=subject,
            subject_version=subject.current_version,
            status=SubjectReview.Status.PENDING,
        ).count()
        == 1
    )
    assert not SubjectReview.objects.filter(
        subject=subject,
        status=SubjectReview.Status.APPROVED,
        subject_version=subject.current_version,
    ).exists()


def test_review_scope_is_own_role_all_and_out_of_scope_object_is_hidden():
    root, _, _ = publish_matching_catalog()
    customers = []
    reviews = []
    for phone in ("13800138001", "13800138002", "13800138003"):
        customer, _, subject_data = create_and_commit_flagged_subject(phone)
        customers.append(customer)
        reviews.append(SubjectReview.objects.get(subject_id=subject_data["id"]))

    role_scope = create_role(
        actor_id=root.id,
        name="Risk role scope",
        description="",
        data_scope=AdminRole.DataScope.ROLE,
        request_id=uuid.uuid4(),
    )
    own_scope = create_role(
        actor_id=root.id,
        name="Risk own scope",
        description="",
        data_scope=AdminRole.DataScope.OWN,
        request_id=uuid.uuid4(),
    )
    view_permission = AdminPermission.objects.get(key="subject_reviews.view")
    AdminRolePermission.objects.bulk_create(
        [
            AdminRolePermission(role=role_scope, permission=view_permission),
            AdminRolePermission(role=own_scope, permission=view_permission),
        ]
    )
    first = create_admin(
        actor_id=root.id,
        phone="13600136001",
        nickname="Role reviewer A",
        password=PASSWORD,
        role_id=role_scope.id,
        request_id=uuid.uuid4(),
    )
    second = create_admin(
        actor_id=root.id,
        phone="13600136002",
        nickname="Role reviewer B",
        password=PASSWORD,
        role_id=role_scope.id,
        request_id=uuid.uuid4(),
    )
    own = create_admin(
        actor_id=root.id,
        phone="13600136003",
        nickname="Own reviewer",
        password=PASSWORD,
        role_id=own_scope.id,
        request_id=uuid.uuid4(),
    )
    CustomerAssignment.objects.create(customer=customers[0], owner_admin=first)
    CustomerAssignment.objects.create(customer=customers[1], owner_admin=second)
    CustomerAssignment.objects.create(customer=customers[2], owner_admin=own)

    role_ids = set(
        scoped_reviews(
            user=first.user, admin_context=resolve_admin_context(first.user)
        ).values_list("id", flat=True)
    )
    own_ids = set(
        scoped_reviews(user=own.user, admin_context=resolve_admin_context(own.user)).values_list(
            "id", flat=True
        )
    )
    all_ids = set(
        scoped_reviews(user=root, admin_context=resolve_admin_context(root)).values_list(
            "id", flat=True
        )
    )
    assert role_ids == {reviews[0].id, reviews[1].id}
    assert own_ids == {reviews[2].id}
    assert {review.id for review in reviews} <= all_ids

    hidden = admin_client(own.user).get(f"/api/v1/admin/subject-reviews/{reviews[0].id}")
    assert hidden.status_code == 404


def test_historical_assessment_keeps_revision_while_current_policy_controls_features():
    requester, first_approver, first_revision = publish_matching_catalog()
    _, _, subject_data = create_and_commit_flagged_subject()
    subject = Subject.objects.select_related("current_version").get(pk=subject_data["id"])
    assessment = SubjectRiskAssessment.objects.get(subject_version=subject.current_version)
    assert assessment.catalog_revision_id == first_revision.id
    review = SubjectReview.objects.get(assessment=assessment)
    decision = admin_client(first_approver).post(
        f"/api/v1/admin/subject-reviews/{review.id}/approve",
        {"expected_version": review.version, "reason": ""},
        format="json",
    )
    assert decision.status_code == 200
    assert capabilities_for_subject(subject).geo_detection is False

    risk_type = SubjectRiskType.objects.get(key="test.review_required")
    updated = admin_client(requester).patch(
        f"/api/v1/admin/subject-risk-types/{risk_type.id}",
        {
            "expected_catalog_version": 4,
            "expected_version": risk_type.version,
            "allow_geo_detection": True,
        },
        format="json",
    )
    assert updated.status_code == 200
    requested = admin_client(requester).post(
        "/api/v1/admin/subject-risk-catalog/publish",
        {"expected_catalog_version": 5},
        format="json",
    )
    assert requested.status_code == 202
    approver = User.objects.create_superuser(
        phone="13500135000", nickname="Second publisher", password=PASSWORD
    )
    approved = admin_client(approver).post(
        f"/api/v1/admin/approvals/{payload(requested)['approval_id']}/approve",
        {"current_password": PASSWORD},
        format="json",
    )
    assert approved.status_code == 200

    assessment.refresh_from_db()
    assert assessment.catalog_revision_id == first_revision.id
    assert assessment.hits.count() == 1
    assert capabilities_for_subject(subject).geo_detection is True
