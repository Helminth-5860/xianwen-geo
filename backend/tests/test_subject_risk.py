import pytest
from django.apps import apps as django_apps
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.admin_rbac.models import AuditEvent, RiskAction
from apps.subjects import version_services
from apps.subjects.models import (
    Subject,
    SubjectEvent,
    SubjectName,
    SubjectProduct,
    SubjectReview,
    SubjectReviewEvent,
    SubjectRiskAssessment,
    SubjectRiskCatalogRevision,
    SubjectRiskCatalogState,
    SubjectRiskHit,
    SubjectRiskType,
    SubjectType,
    SubjectVersion,
)
from apps.subjects.risk_engine import (
    RiskCatalogInvalid,
    evaluate_catalog,
    normalize_patterns,
)
from apps.subjects.risk_services import (
    SubjectReviewPending,
    SubjectReviewRejected,
    SubjectRiskError,
    assess_existing_subject_versions,
    capabilities_for_subject,
    merge_feature_policies,
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
        {"expected_catalog_version": 3, "confirmed": True},
        format="json",
    )
    assert requested.status_code == 200
    revision = SubjectRiskCatalogState.objects.get(pk=1).published_revision
    assert revision.draft_version == 3
    assert payload(requested)["revision_id"] == str(revision.id)
    assert AuditEvent.objects.get(action_key="subject_risk.catalog.publish").outcome == "executed"
    return requester, approver, revision


def create_flagged_subject(phone="13800138000"):
    user = User.objects.create_user(
        phone=phone,
        nickname="Subject owner",
        password=PASSWORD,
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
    return user, client, payload(created)


def create_and_commit_flagged_subject(phone="13800138000"):
    user, client, detail = create_flagged_subject(phone)
    committed = client.post(
        f"/api/v1/subjects/{detail['id']}/commit",
        {"expected_version": detail["version"], "products": []},
        format="json",
    )
    assert committed.status_code == 201
    return user, client, payload(committed)["subject"]


@pytest.mark.django_db
def test_catalog_is_draft_until_confirmed_direct_publish():
    requester, _, revision = publish_matching_catalog()

    action = RiskAction.objects.get(pk="subject_risk.catalog.publish")
    assert action.supported_modes == ["confirm"]
    assert action.default_mode == "confirm"
    assert action.minimum_mode == "confirm"
    assert action.policy.current_mode == "confirm"
    assert revision.revision_no == 1
    assert revision.snapshot["rules"][0]["operator"] == "contains_any"

    generic = admin_client(requester).post(
        "/api/v1/admin/approvals",
        {"action_key": "subject_risk.catalog.publish", "payload": {}},
        format="json",
    )
    assert generic.status_code == 404


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
        {"expected_version": review.version, "public_reason": "", "internal_note": ""},
        format="json",
    )
    assert decision.status_code == 200
    review.refresh_from_db()
    assert review.status == SubjectReview.Status.APPROVED
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
        {"expected_version": old_review.version, "public_reason": "", "internal_note": ""},
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
        {
            "expected_version": review.version,
            "public_reason": "Test rejection",
            "internal_note": "Internal evidence",
        },
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


@pytest.mark.django_db
def test_commit_without_published_catalog_returns_503_and_rolls_back_all_version_facts():
    _, client, detail = create_flagged_subject()

    response = client.post(
        f"/api/v1/subjects/{detail['id']}/commit",
        {"expected_version": detail["version"], "products": []},
        format="json",
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SUBJECT_RISK_CONFIG_INTEGRITY_ERROR"
    subject = Subject.objects.get(pk=detail["id"])
    assert subject.current_version_id is None
    assert subject.version == detail["version"]
    assert not SubjectVersion.objects.filter(subject=subject).exists()
    assert not SubjectName.objects.exists()
    assert not SubjectProduct.objects.exists()
    assert not SubjectEvent.objects.filter(
        event_type=SubjectEvent.EventType.VERSION_COMMITTED
    ).exists()
    assert not SubjectRiskAssessment.objects.exists()
    assert not SubjectReview.objects.exists()


@pytest.mark.django_db
def test_draft_changes_do_not_affect_runtime_until_confirmed_publish():
    requester, approver, revision = publish_matching_catalog()
    _, _, subject_data = create_and_commit_flagged_subject()
    review = SubjectReview.objects.get(subject_id=subject_data["id"])
    decided = admin_client(approver).post(
        f"/api/v1/admin/subject-reviews/{review.id}/approve",
        {"expected_version": review.version, "public_reason": "", "internal_note": ""},
        format="json",
    )
    assert decided.status_code == 200
    subject = Subject.objects.select_related("current_version").get(pk=subject_data["id"])
    assert capabilities_for_subject(subject).geo_detection is False

    risk_type = SubjectRiskType.objects.get(key="test.review_required")
    changed = admin_client(requester).patch(
        f"/api/v1/admin/subject-risk-types/{risk_type.id}",
        {
            "expected_catalog_version": 4,
            "expected_version": risk_type.version,
            "allow_geo_detection": True,
        },
        format="json",
    )
    assert changed.status_code == 200
    assert capabilities_for_subject(subject).geo_detection is False

    requested = admin_client(requester).post(
        "/api/v1/admin/subject-risk-catalog/publish",
        {"expected_catalog_version": 5, "confirmed": True},
        format="json",
    )
    assert requested.status_code == 200
    second_revision = SubjectRiskCatalogRevision.objects.get(pk=payload(requested)["revision_id"])
    assert second_revision.draft_version == 5

    risk_type.refresh_from_db()
    changed_again = admin_client(requester).patch(
        f"/api/v1/admin/subject-risk-types/{risk_type.id}",
        {
            "expected_catalog_version": 6,
            "expected_version": risk_type.version,
            "allow_article_generation": True,
        },
        format="json",
    )
    assert changed_again.status_code == 200
    state = SubjectRiskCatalogState.objects.get(pk=1)
    assert state.published_revision_id == second_revision.id
    assert state.published_revision_id != revision.id
    assert SubjectRiskCatalogRevision.objects.count() == 2


@pytest.mark.django_db
def test_current_feature_policy_merges_deny_and_requirements_and_missing_key_fails_closed():
    def policy(*, allow=True, citations=False, disclaimer=False):
        return {
            "allow_geo_detection": allow,
            "allow_article_generation": allow,
            "allow_image_generation": allow,
            "require_authoritative_citations": citations,
            "require_disclaimer": disclaimer,
        }

    clear = merge_feature_policies(policies={}, hit_keys=[])
    assert clear.geo_detection is True
    assert clear.article_generation is True
    assert clear.require_disclaimer is False

    merged = merge_feature_policies(
        policies={
            "test.a": policy(allow=True, citations=True),
            "test.b": policy(allow=False, disclaimer=True),
        },
        hit_keys=["test.a", "test.b"],
    )
    assert merged.geo_detection is False
    assert merged.article_generation is False
    assert merged.image_generation is False
    assert merged.require_authoritative_citations is True
    assert merged.require_disclaimer is True

    with pytest.raises(SubjectRiskError):
        merge_feature_policies(policies={"test.a": policy()}, hit_keys=["test.missing"])


@pytest.mark.django_db
def test_review_public_reason_internal_note_and_evidence_have_separate_api_boundaries():
    _, approver, _ = publish_matching_catalog()
    owner, _, subject_data = create_and_commit_flagged_subject()
    review = SubjectReview.objects.get(subject_id=subject_data["id"])

    decision = admin_client(approver).post(
        f"/api/v1/admin/subject-reviews/{review.id}/reject",
        {
            "expected_version": review.version,
            "public_reason": "请核对公开主体资料",
            "internal_note": "仅管理员可见的核验线索",
        },
        format="json",
    )
    assert decision.status_code == 200
    admin_data = payload(decision)
    assert admin_data["public_reason"] == "请核对公开主体资料"
    assert admin_data["internal_note"] == "仅管理员可见的核验线索"
    assert admin_data["review_evidence"] == [
        {
            "risk_type_key": "test.review_required",
            "rule_key": "test.name_contains",
            "reason_type": "data_conflict",
            "field_key": "name",
        }
    ]
    assert "patterns" not in str(admin_data)
    assert "field_values" not in str(admin_data)

    user_detail = user_client(owner).get(f"/api/v1/subjects/{subject_data['id']}")
    assert user_detail.status_code == 200
    user_data = payload(user_detail)
    assert user_data["risk"] == {
        "status": "rejected",
        "review_id": str(review.id),
        "public_reason": "请核对公开主体资料",
    }
    encoded = str(user_data)
    assert "仅管理员可见的核验线索" not in encoded
    assert "review_evidence" not in encoded
    assert "test.name_contains" not in encoded


@pytest.mark.django_db
@pytest.mark.parametrize(
    "failure_point",
    ["current_version", "subject_event", "assessment", "hit", "review", "review_event"],
)
def test_subject_commit_risk_fact_failures_roll_back_every_formal_fact(monkeypatch, failure_point):
    publish_matching_catalog()
    _, client, detail = create_flagged_subject()

    def fail(*args, **kwargs):
        raise RuntimeError(f"injected {failure_point} failure")

    if failure_point == "current_version":
        original_save = Subject.save

        def fail_current_version(instance, *args, **kwargs):
            if instance.current_version_id is not None:
                fail()
            return original_save(instance, *args, **kwargs)

        monkeypatch.setattr(Subject, "save", fail_current_version)
    else:
        managers = {
            "subject_event": (SubjectEvent.objects, "create"),
            "assessment": (SubjectRiskAssessment.objects, "create"),
            "hit": (SubjectRiskHit.objects, "bulk_create"),
            "review": (SubjectReview.objects, "create"),
            "review_event": (SubjectReviewEvent.objects, "create"),
        }
        manager, method = managers[failure_point]
        monkeypatch.setattr(manager, method, fail)

    response = client.post(
        f"/api/v1/subjects/{detail['id']}/commit",
        {"expected_version": detail["version"], "products": []},
        format="json",
    )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    subject = Subject.objects.get(pk=detail["id"])
    assert subject.current_version_id is None
    assert subject.version == detail["version"]
    assert not SubjectVersion.objects.filter(subject=subject).exists()
    assert not SubjectName.objects.exists()
    assert not SubjectProduct.objects.exists()
    assert not SubjectEvent.objects.filter(
        event_type=SubjectEvent.EventType.VERSION_COMMITTED
    ).exists()
    assert not SubjectRiskAssessment.objects.exists()
    assert not SubjectRiskHit.objects.exists()
    assert not SubjectReview.objects.exists()
    assert not SubjectReviewEvent.objects.exists()


@pytest.mark.django_db
def test_existing_version_batch_uses_one_revision_and_reviews_only_current_version(monkeypatch):
    _, _, revision = publish_matching_catalog()
    _, client, detail = create_flagged_subject()
    original_assess = version_services.assess_subject_version
    monkeypatch.setattr(version_services, "assess_subject_version", lambda **kwargs: None)

    first = client.post(
        f"/api/v1/subjects/{detail['id']}/commit",
        {"expected_version": detail["version"], "products": []},
        format="json",
    )
    assert first.status_code == 201
    first_subject = payload(first)["subject"]
    draft = client.patch(
        f"/api/v1/subjects/{detail['id']}/draft",
        {"expected_version": first_subject["version"], "values": {"name": "Flagged v2"}},
        format="json",
    )
    second = client.post(
        f"/api/v1/subjects/{detail['id']}/commit",
        {"expected_version": payload(draft)["version"], "products": []},
        format="json",
    )
    assert second.status_code == 201
    monkeypatch.setattr(version_services, "assess_subject_version", original_assess)
    assert SubjectRiskAssessment.objects.count() == 0

    call_command("assess_existing_subject_versions", verbosity=0)
    assert SubjectRiskAssessment.objects.count() == 0
    result = assess_existing_subject_versions()

    assert result == {
        "revision_id": str(revision.id),
        "assessed": 2,
        "reviews_created": 1,
    }
    versions = list(SubjectVersion.objects.order_by("version_no"))
    assessments = list(SubjectRiskAssessment.objects.order_by("subject_version__version_no"))
    assert [item.catalog_revision_id for item in assessments] == [revision.id, revision.id]
    assert not SubjectReview.objects.filter(subject_version=versions[0]).exists()
    assert (
        SubjectReview.objects.filter(
            subject_version=versions[1], status=SubjectReview.Status.PENDING
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_catalog_binding_migration_refuses_to_guess_existing_revision_evidence():
    publish_matching_catalog()
    import importlib

    migration = importlib.import_module(
        "apps.subjects.migrations.0011_catalog_publish_binding_and_review_boundaries"
    )

    with pytest.raises(RuntimeError, match="will not be guessed"):
        migration.reject_existing_revisions(django_apps, None)


@pytest.mark.django_db
def test_feature_state_matrix_pending_and_rejected_are_fail_closed():
    _, approver, _ = publish_matching_catalog()
    _, _, subject_data = create_and_commit_flagged_subject()
    subject = Subject.objects.select_related("current_version").get(pk=subject_data["id"])
    review = SubjectReview.objects.get(subject=subject)

    with pytest.raises(SubjectReviewPending):
        capabilities_for_subject(subject)

    rejected = admin_client(approver).post(
        f"/api/v1/admin/subject-reviews/{review.id}/reject",
        {
            "expected_version": review.version,
            "public_reason": "公开拒绝原因",
            "internal_note": "内部说明",
        },
        format="json",
    )
    assert rejected.status_code == 200
    subject = Subject.objects.select_related("current_version").get(pk=subject.id)
    with pytest.raises(SubjectReviewRejected):
        capabilities_for_subject(subject)


@pytest.mark.django_db
def test_current_catalog_missing_a_historical_hit_policy_fails_closed(monkeypatch):
    _, approver, _ = publish_matching_catalog()
    _, _, subject_data = create_and_commit_flagged_subject()
    review = SubjectReview.objects.get(subject_id=subject_data["id"])
    approved = admin_client(approver).post(
        f"/api/v1/admin/subject-reviews/{review.id}/approve",
        {"expected_version": review.version, "public_reason": "", "internal_note": ""},
        format="json",
    )
    assert approved.status_code == 200
    subject = Subject.objects.select_related("current_version").get(pk=subject_data["id"])
    import apps.subjects.risk_services as services

    current_without_historical_policy = type(
        "Revision", (), {"snapshot": {"format_version": 1, "risk_types": [], "rules": []}}
    )()
    monkeypatch.setattr(
        services, "published_catalog_revision", lambda: current_without_historical_policy
    )

    with pytest.raises(SubjectRiskError):
        capabilities_for_subject(subject)


@pytest.mark.django_db
def test_subject_risk_seed_and_migration_do_not_invent_catalog_or_history():
    state = SubjectRiskCatalogState.objects.get(pk=1)
    assert state.version == 1
    assert state.published_revision_id is None
    assert not SubjectRiskType.objects.exists()
    assert not SubjectRiskCatalogRevision.objects.exists()
    assert not SubjectRiskAssessment.objects.exists()
    assert not SubjectReview.objects.exists()
