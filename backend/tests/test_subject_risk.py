import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.admin_rbac.models import ApprovalRequest, AuditEvent, RiskAction
from apps.subjects.models import (
    Subject,
    SubjectReview,
    SubjectReviewEvent,
    SubjectRiskAssessment,
    SubjectRiskCatalogRevision,
    SubjectRiskCatalogState,
    SubjectType,
)
from apps.subjects.risk_engine import (
    RiskCatalogInvalid,
    evaluate_catalog,
    normalize_patterns,
)
from apps.users.models import Notification, User
from tests.admin_session_helpers import authenticate_admin_client

PASSWORD = "Correct-Horse-Battery-2026!"


@pytest.fixture(autouse=True)
def catalogs():
    call_command("sync_admin_rbac", "--apply", verbosity=0)
    call_command("sync_subject_catalog", "--apply", verbosity=0)


def make_superuser(phone):
    return User.objects.create_superuser(
        phone=phone,
        nickname="Risk administrator",
        password=PASSWORD,
    )


def admin_client(user, *, csrf=False):
    return authenticate_admin_client(APIClient(enforce_csrf_checks=csrf), user)


def user_client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def payload(response):
    return response.json()["data"]


def publish_matching_catalog(*, pattern="flagged"):
    requester = make_superuser("13900139000")
    approver = make_superuser("13700137000")
    requester_client = admin_client(requester)

    created_type = requester_client.post(
        "/api/v1/admin/subject-risk-types",
        {
            "expected_catalog_version": 1,
            "key": "test.review_required",
            "name": "Test review required",
            "description": "Test-only catalog entry",
            "enabled": True,
            "manual_review_required": True,
            "allow_geo_detection": False,
            "allow_article_generation": False,
            "allow_image_generation": False,
            "require_authoritative_citations": True,
            "require_disclaimer": True,
            "sort_order": 10,
        },
        format="json",
    )
    assert created_type.status_code == 201
    risk_type_id = payload(created_type)["id"]

    created_rule = requester_client.post(
        "/api/v1/admin/subject-risk-rules",
        {
            "expected_catalog_version": 2,
            "key": "test.name_contains",
            "risk_type": risk_type_id,
            "subject_type": None,
            "field_key": "name",
            "operator": "contains_any",
            "patterns": [pattern],
            "reason_type": "data_conflict",
            "enabled": True,
            "priority": 10,
        },
        format="json",
    )
    assert created_rule.status_code == 201

    requested = requester_client.post(
        "/api/v1/admin/subject-risk-catalog/publish",
        {"expected_catalog_version": 3},
        format="json",
    )
    assert requested.status_code == 202
    approval_id = payload(requested)["approval_id"]
    assert ApprovalRequest.objects.get(pk=approval_id).status == ApprovalRequest.Status.PENDING
    assert not SubjectRiskCatalogRevision.objects.exists()

    approved = admin_client(approver).post(
        f"/api/v1/admin/approvals/{approval_id}/approve",
        {"current_password": PASSWORD},
        format="json",
    )
    assert approved.status_code == 200
    approval = ApprovalRequest.objects.get(pk=approval_id)
    assert approval.status == ApprovalRequest.Status.EXECUTED
    revision = SubjectRiskCatalogState.objects.get(pk=1).published_revision
    assert revision.approval_request_id == approval.id
    return requester, approver, revision


def create_and_commit_flagged_subject(phone="13800138000"):
    user = User.objects.create_user(
        phone=phone,
        nickname="Subject owner",
        password=PASSWORD,
        approval_status=User.ApprovalStatus.PENDING,
    )
    client = user_client(user)
    subject_type = SubjectType.objects.get(key="enterprise")
    created = client.post(
        "/api/v1/subjects",
        {
            "subject_type_id": str(subject_type.pk),
            "expected_schema_version": subject_type.schema_version,
            "initial_values": {"name": "Flagged example"},
        },
        format="json",
    )
    assert created.status_code == 201
    detail = payload(created)
    committed = client.post(
        f"/api/v1/subjects/{detail['id']}/commit",
        {"expected_version": detail["version"], "products": []},
        format="json",
    )
    assert committed.status_code == 201
    return user, client, payload(committed)["subject"]


@pytest.mark.django_db
def test_catalog_is_draft_until_two_person_publish_and_only_fixed_action_can_activate():
    requester, _, revision = publish_matching_catalog()

    action = RiskAction.objects.get(pk="subject_risk.catalog.publish")
    assert action.supported_modes == ["two_person"]
    assert action.default_mode == "two_person"
    assert action.minimum_mode == "two_person"
    assert action.policy.current_mode == "two_person"
    assert revision.revision_no == 1
    assert revision.snapshot["rules"][0]["operator"] == "contains_any"

    generic = admin_client(requester).post(
        "/api/v1/admin/approvals",
        {"action_key": "subject_risk.catalog.publish", "payload": {}},
        format="json",
    )
    assert generic.status_code == 405


@pytest.mark.django_db
def test_rule_language_rejects_regex_urls_scripts_and_unknown_operators():
    assert normalize_patterns(["  Example  "]) == ["example"]
    for forbidden in ("https://example.invalid", "<script>alert(1)</script>", "{{dynamic}}"):
        with pytest.raises(RiskCatalogInvalid):
            normalize_patterns([forbidden])
    snapshot = {
        "format_version": 1,
        "risk_types": [
            {
                "key": "test.type",
                "enabled": True,
                "manual_review_required": False,
                "allow_geo_detection": False,
                "allow_article_generation": False,
                "allow_image_generation": False,
                "require_authoritative_citations": True,
                "require_disclaimer": True,
            }
        ],
        "rules": [
            {
                "key": "test.rule",
                "risk_type_key": "test.type",
                "subject_type_key": None,
                "field_key": "name",
                "operator": "regex",
                "patterns": ["x"],
                "reason_type": "data_conflict",
                "enabled": True,
            }
        ],
    }
    with pytest.raises(RiskCatalogInvalid):
        evaluate_catalog(
            snapshot=snapshot,
            subject_type_key="enterprise",
            schema_snapshot={"fields": []},
            field_values={},
        )


@pytest.mark.django_db
def test_commit_binds_immutable_revision_and_direct_review_supersedes_only_pending():
    _, approver, revision = publish_matching_catalog()
    _, client, subject_data = create_and_commit_flagged_subject()
    subject = Subject.objects.select_related("current_version").get(pk=subject_data["id"])
    assessment = SubjectRiskAssessment.objects.get(subject_version=subject.current_version)
    review = SubjectReview.objects.get(assessment=assessment)

    assert assessment.catalog_revision_id == revision.id
    assert assessment.semantic_digest == subject.current_version.semantic_digest
    assert assessment.outcome == SubjectRiskAssessment.Outcome.REVIEW_REQUIRED
    assert review.status == SubjectReview.Status.PENDING
    assert review.assessment.hits.values_list("reason_type", flat=True).get() == "data_conflict"

    decision = admin_client(approver).post(
        f"/api/v1/admin/subject-reviews/{review.id}/approve",
        {"expected_version": review.version, "reason": ""},
        format="json",
    )
    assert decision.status_code == 200
    review.refresh_from_db()
    assert review.status == SubjectReview.Status.APPROVED
    assert not ApprovalRequest.objects.filter(target_id=review.id).exists()
    assert AuditEvent.objects.filter(
        action_key="subject_risk.review.approved", target_id=review.id
    ).exists()
    assert Notification.objects.filter(
        recipient=subject.user,
        notification_type=Notification.NotificationType.SUBJECT_REVIEW_APPROVED,
    ).exists()

    draft = client.patch(
        f"/api/v1/subjects/{subject.id}/draft",
        {"expected_version": subject.version, "values": {"name": "Flagged changed"}},
        format="json",
    )
    assert draft.status_code == 200
    changed = payload(draft)
    second = client.post(
        f"/api/v1/subjects/{subject.id}/commit",
        {"expected_version": changed["version"], "products": []},
        format="json",
    )
    assert second.status_code == 201
    review.refresh_from_db()
    assert review.status == SubjectReview.Status.APPROVED
    assert (
        SubjectReview.objects.filter(subject=subject, status=SubjectReview.Status.PENDING).count()
        == 1
    )


@pytest.mark.django_db
def test_new_version_supersedes_pending_review_and_old_review_cannot_authorize():
    _, approver, _ = publish_matching_catalog()
    _, client, subject_data = create_and_commit_flagged_subject()
    subject = Subject.objects.get(pk=subject_data["id"])
    old_review = SubjectReview.objects.get(subject=subject)

    updated = client.patch(
        f"/api/v1/subjects/{subject.id}/draft",
        {"expected_version": subject.version, "values": {"name": "Flagged second"}},
        format="json",
    )
    second = client.post(
        f"/api/v1/subjects/{subject.id}/commit",
        {"expected_version": payload(updated)["version"], "products": []},
        format="json",
    )
    assert second.status_code == 201
    old_review.refresh_from_db()
    assert old_review.status == SubjectReview.Status.SUPERSEDED
    assert (
        SubjectReviewEvent.objects.filter(
            review=old_review, event_type=SubjectReviewEvent.EventType.SUPERSEDED
        ).count()
        == 1
    )

    stale = admin_client(approver).post(
        f"/api/v1/admin/subject-reviews/{old_review.id}/approve",
        {"expected_version": old_review.version, "reason": ""},
        format="json",
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "SUBJECT_REVIEW_STATE_CONFLICT"


@pytest.mark.django_db
def test_review_api_requires_secure_admin_csrf_and_exposes_no_subject_values():
    _, approver, _ = publish_matching_catalog()
    _, _, subject_data = create_and_commit_flagged_subject()
    review = SubjectReview.objects.get(subject_id=subject_data["id"])

    unauthenticated = APIClient().get("/api/v1/admin/subject-reviews")
    assert unauthenticated.status_code == 401

    csrf_client = admin_client(approver, csrf=True)
    csrf_failed = csrf_client.post(
        f"/api/v1/admin/subject-reviews/{review.id}/reject",
        {"expected_version": review.version, "reason": "Test rejection"},
        format="json",
    )
    assert csrf_failed.status_code == 403
    assert csrf_failed.json()["error"]["code"] == "CSRF_FAILED"

    detail = admin_client(approver).get(f"/api/v1/admin/subject-reviews/{review.id}")
    assert detail.status_code == 200
    encoded = str(detail.json()).casefold()
    assert "field_values" not in encoded
    assert "schema_snapshot" not in encoded
    assert "semantic_digest" not in encoded
