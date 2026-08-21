from __future__ import annotations

import io
import json
import uuid
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from apps.admin_rbac.models import (
    AdminPermission,
    AdminRole,
    AdminRolePermission,
    AuditEvent,
    CustomerAssignment,
)
from apps.admin_rbac.services import create_admin
from apps.documents.scanners import ClamAVFileScanner
from apps.operations.models import (
    Announcement,
    CustomerContactLog,
    CustomerFollowup,
    CustomerStatus,
    SupportViewAuditLog,
    SupportViewRequest,
    SystemAlert,
)
from apps.users.models import User
from tests.admin_session_helpers import authenticate_admin_client

PASSWORD = "Correct-Horse-Battery-2026!"


@pytest.fixture(autouse=True)
def sync_permissions():
    call_command("sync_admin_rbac", "--apply", verbosity=0)


def make_superuser():
    return User.objects.create_superuser(
        phone="13900000001", nickname="Stage3 管理员", password=PASSWORD
    )


def make_customer(phone="13800000001"):
    return User.objects.create_user(
        phone=phone,
        nickname="Stage3 客户",
        password=PASSWORD,
        approval_status=User.ApprovalStatus.APPROVED,
    )


def admin_client(user=None, *, csrf=False):
    client = APIClient(enforce_csrf_checks=csrf)
    return authenticate_admin_client(client, user or make_superuser())


def user_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def data(response):
    return response.json()["data"]


@pytest.mark.django_db
def test_customer_profile_contact_followup_and_audit_are_scoped_and_versioned():
    customer = make_customer()
    client = admin_client()
    status = CustomerStatus.objects.get(key="formal")

    updated = client.patch(
        f"/api/v1/admin/operations/customers/{customer.pk}",
        {
            "expected_version": 1,
            "status_id": str(status.pk),
            "source": "referral",
            "internal_note": "仅运营可见",
            "tag_ids": [],
        },
        format="json",
    )
    assert updated.status_code == 200
    assert data(updated)["profile"]["status"]["key"] == "formal"
    assert data(updated)["profile"]["version"] == 2

    stale = client.patch(
        f"/api/v1/admin/operations/customers/{customer.pk}",
        {"expected_version": 1, "source": "stale"},
        format="json",
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["details"]["operations_code"] == (
        "CUSTOMER_PROFILE_VERSION_CONFLICT"
    )

    contacted_at = timezone.now()
    contact_response = client.post(
        f"/api/v1/admin/operations/customers/{customer.pk}/contacts",
        {
            "contacted_at": contacted_at.isoformat(),
            "method": "phone",
            "content": "已确认试用反馈",
            "next_followup_at": (contacted_at + timedelta(days=1)).isoformat(),
            "followup_note": "明日回访",
        },
        format="json",
    )
    assert contact_response.status_code == 201
    contact = CustomerContactLog.objects.get()
    assert CustomerFollowup.objects.filter(source_contact=contact, status="open").exists()
    with pytest.raises(TypeError):
        contact.content = "tampered"
        contact.save()
    assert AuditEvent.objects.filter(action_key="customer.profile.update").exists()
    assert AuditEvent.objects.filter(action_key="customer.contact.create").exists()


@pytest.mark.django_db
def test_announcements_feedback_and_support_view_enforce_owner_and_read_only_audit():
    admin = make_superuser()
    customer = make_customer()
    other = make_customer("13800000002")
    client = admin_client(admin)

    created = client.post(
        "/api/v1/admin/announcements",
        {
            "title": "维护通知",
            "body": "今晚进行例行维护。",
            "audience": "user",
            "audience_keys": [str(customer.pk)],
        },
        format="json",
    )
    assert created.status_code == 201
    announcement = Announcement.objects.get()
    published = client.post(
        f"/api/v1/admin/announcements/{announcement.pk}/action",
        {"expected_version": 1, "action": "publish"},
        format="json",
    )
    assert published.status_code == 200
    assert len(data(user_client(customer).get("/api/v1/announcements"))) == 1
    assert data(user_client(other).get("/api/v1/announcements")) == []

    feedback = user_client(customer).post(
        "/api/v1/feedback",
        {"module": "geo.report", "description": "希望增加状态说明。"},
        format="json",
    )
    assert feedback.status_code == 201
    feedback_id = data(feedback)["id"]
    assert user_client(other).get(f"/api/v1/feedback/{feedback_id}").status_code == 404
    replied = client.post(
        f"/api/v1/admin/feedback/{feedback_id}/action",
        {"expected_version": 1, "action": "reply", "reply": "已记录并进入评估。"},
        format="json",
    )
    assert replied.status_code == 200
    assert data(replied)["status"] == "replied"

    support = client.post(
        f"/api/v1/admin/users/{customer.pk}/support-view-request",
        {"reason": "协助定位用户报告读取问题", "forced": False},
        format="json",
    )
    assert support.status_code == 202
    support_id = data(support)["id"]
    assert SupportViewRequest.objects.get(pk=support_id).status == "pending"
    authorized = user_client(customer).post(
        f"/api/v1/support-view-requests/{support_id}/decision",
        {"expected_version": 1, "decision": "authorize"},
        format="json",
    )
    assert authorized.status_code == 200
    summary = client.get(f"/api/v1/admin/support-view-sessions/{support_id}/summary")
    assert summary.status_code == 200
    assert data(summary)["read_only"] is True
    assert "phone" not in data(summary)
    assert SupportViewAuditLog.objects.filter(
        support_request_id=support_id, page_key="summary"
    ).exists()
    assert AuditEvent.objects.filter(action_key="support_view.user.authorize").exists()


@pytest.mark.django_db
def test_release_readiness_is_admin_only_fail_closed_and_contains_no_secret_material():
    ordinary = make_customer()
    denied = user_client(ordinary).get("/api/v1/admin/release-readiness")
    assert denied.status_code == 403

    response = admin_client().get("/api/v1/admin/release-readiness")
    assert response.status_code == 200
    payload = data(response)
    assert payload["status"] == "NOT_READY"
    assert payload["secrets_included"] is False
    serialized = json.dumps(payload).lower()
    for forbidden in ("api_key", "secret_key", "authorization", "password", "raw_provider"):
        assert forbidden not in serialized
    checks = {item["key"]: item for item in payload["checks"]}
    assert checks["private_storage"]["status"] == "NOT_READY"
    assert checks["sms"]["status"] == "NOT_READY"
    assert checks["workers"]["status"] == "NOT_READY"
    assert checks["backup_recovery"]["status"] == "NOT_READY"
    assert checks["external_gate_evidence"]["status"] == "NOT_READY"


@pytest.mark.django_db
def test_security_headers_and_bounded_task_projection():
    customer = make_customer()
    response = user_client(customer).get("/api/v1/usage-records")
    assert response.status_code == 200
    assert data(response)["tasks"] == []
    assert response["Content-Security-Policy"].startswith("default-src 'none'")
    assert response["Referrer-Policy"] == "no-referrer"
    assert "camera=()" in response["Permissions-Policy"]


@pytest.mark.django_db
def test_clamav_scanner_uses_bounded_instream_protocol(monkeypatch, settings):
    class FakeSocket:
        def __init__(self, response):
            self.response = response
            self.sent = bytearray()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def settimeout(self, timeout):
            assert timeout == 10

        def sendall(self, data):
            self.sent.extend(data)

        def recv(self, size):
            assert size == 4096
            return self.response

    fake = FakeSocket(b"stream: OK\0")
    monkeypatch.setattr("apps.documents.scanners.socket.create_connection", lambda *a, **k: fake)
    settings.CLAMAV_HOST = "clamav"
    settings.CLAMAV_PORT = 3310
    settings.CLAMAV_TIMEOUT_SECONDS = 10
    result = ClamAVFileScanner().scan(io.BytesIO(b"safe document"))
    assert result.status == "clean"
    assert fake.sent.startswith(b"zINSTREAM\0")
    assert fake.sent.endswith(b"\0\0\0\0")


@pytest.mark.django_db
def test_operations_customer_views_enforce_admin_data_scope():
    actor = make_superuser()
    role = AdminRole.objects.create(name="Stage3 本人客户", data_scope=AdminRole.DataScope.OWN)
    permissions = AdminPermission.objects.filter(
        key__in=("operations.customers.view", "operations.customers.manage")
    )
    AdminRolePermission.objects.bulk_create(
        AdminRolePermission(role=role, permission=permission) for permission in permissions
    )
    profile = create_admin(
        actor_id=actor.pk,
        phone="13700000001",
        nickname="Stage3 客户经理",
        password=PASSWORD,
        role_id=role.pk,
        request_id=uuid.uuid4(),
    )
    visible = make_customer()
    hidden = make_customer("13800000002")
    CustomerAssignment.objects.create(customer=visible, owner_admin=profile)
    client = admin_client(profile.user)

    listed = data(client.get("/api/v1/admin/operations/customers"))
    assert {item["id"] for item in listed["items"]} == {str(visible.pk)}
    assert client.get(f"/api/v1/admin/operations/customers/{hidden.pk}").status_code == 404
    assert (
        client.patch(
            f"/api/v1/admin/operations/customers/{hidden.pk}",
            {"expected_version": 1, "source": "scope-bypass"},
            format="json",
        ).status_code
        == 404
    )


@pytest.mark.django_db
def test_customer_catalog_duplicate_key_returns_stable_conflict():
    client = admin_client()
    first = client.post(
        "/api/v1/admin/customer-tags", {"key": "priority", "name": "重点"}, format="json"
    )
    duplicate = client.post(
        "/api/v1/admin/customer-tags", {"key": "priority", "name": "重复"}, format="json"
    )
    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["details"]["operations_code"] == (
        "CUSTOMER_CATALOG_KEY_CONFLICT"
    )

    tag_id = data(first)["id"]
    updated = client.patch(
        f"/api/v1/admin/customer-tags/{tag_id}",
        {"expected_version": 1, "state": "inactive"},
        format="json",
    )
    assert updated.status_code == 200
    assert data(updated)["state"] == "inactive"
    stale = client.patch(
        f"/api/v1/admin/customer-tags/{tag_id}",
        {"expected_version": 1, "name": "过期写入"},
        format="json",
    )
    assert stale.status_code == 409


@pytest.mark.django_db
def test_customer_csv_export_is_confirmed_scoped_masked_formula_safe_and_audited():
    customer = make_customer()
    customer.nickname = '=HYPERLINK("https://invalid.example")'
    customer.save(update_fields=["nickname", "updated_at"])
    client = admin_client()

    invalid = client.post(
        "/api/v1/admin/operations/exports/customers",
        {"format": "csv", "confirmation": "wrong"},
        format="json",
    )
    assert invalid.status_code == 422

    response = client.post(
        "/api/v1/admin/operations/exports/customers",
        {"format": "csv", "confirmation": "EXPORT_SCOPED_CUSTOMERS"},
        format="json",
    )
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    body = response.content.decode("utf-8-sig")
    assert customer.phone not in body
    assert "138****0001" in body
    assert "'=HYPERLINK" in body
    assert AuditEvent.objects.filter(action_key="customer.export.csv").exists()


@pytest.mark.django_db
def test_system_alert_actions_are_versioned_permission_checked_and_audited():
    now = timezone.now()
    alert = SystemAlert.objects.create(
        fingerprint="a" * 64,
        category="worker_health",
        severity=SystemAlert.Severity.CRITICAL,
        safe_summary={"queue": "image_generation"},
        first_seen_at=now,
        last_seen_at=now,
    )
    client = admin_client()
    acknowledged = client.post(
        f"/api/v1/admin/system-alerts/{alert.pk}/action",
        {"expected_version": 1, "action": "acknowledge"},
        format="json",
    )
    assert acknowledged.status_code == 200
    assert data(acknowledged)["status"] == "acknowledged"
    stale = client.post(
        f"/api/v1/admin/system-alerts/{alert.pk}/action",
        {"expected_version": 1, "action": "resolve"},
        format="json",
    )
    assert stale.status_code == 409
    assert AuditEvent.objects.filter(action_key="system_alert.acknowledge").exists()
