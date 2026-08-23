import threading

import pytest
from django.contrib.sessions.middleware import SessionMiddleware
from django.db import close_old_connections, connection
from django.test import RequestFactory
from rest_framework.test import APIClient

from apps.users.authentication import SESSION_VERSION_KEY, AccountUnavailable, start_browser_session
from apps.users.models import Notification, User, UserStatusEvent
from apps.users.permissions import ApprovedAndActive
from apps.users.status_services import (
    AccountStateConflict,
    ApprovalStateConflict,
    change_account_status,
    resubmit_approval,
    review_user,
)
from tests.admin_session_helpers import authenticate_admin_client
from tests.customer_ownership_helpers import assign_test_customer

PASSWORD = "Correct-Horse-Battery-2026!"
CSRF_PATH = "/api/v1/auth/csrf"
LOGIN_PATH = "/api/v1/auth/login/password"
ME_PATH = "/api/v1/me"


def create_user(phone="13800138000", **kwargs):
    created = User.objects.create_user(
        phone=phone,
        nickname=kwargs.pop("nickname", "审核用户"),
        password=kwargs.pop("password", PASSWORD),
        **kwargs,
    )
    if not created.is_staff and not created.is_superuser:
        assign_test_customer(created)
    return created


def create_admin(phone="13900139000", **kwargs):
    return User.objects.create_superuser(
        phone=phone,
        nickname="审核管理员",
        password=PASSWORD,
        **kwargs,
    )


def authenticated_client(user):
    client = APIClient()
    if user.is_superuser:
        return authenticate_admin_client(client, user)
    client.force_authenticate(user=user)
    return client


def browser_client(phone="13800138000"):
    client = APIClient(enforce_csrf_checks=True)
    csrf = client.get(CSRF_PATH).json()["data"]["csrf_token"]
    user = User.objects.filter(phone=phone).first()
    if user is not None and user.is_superuser:
        return authenticate_admin_client(client, user)
    response = client.post(
        LOGIN_PATH,
        {"phone": phone, "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert response.status_code == 200
    return client


@pytest.mark.django_db
def test_admin_list_detail_filters_phone_and_minimizes_fields():
    admin = create_admin()
    first = create_user()
    create_user("13700137000", approval_status=User.ApprovalStatus.APPROVED)
    client = authenticated_client(admin)

    response = client.get(
        "/api/v1/admin/users",
        {"approval_status": "pending", "phone": "0086 138-0013-8000"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["pagination"] == {"page": 1, "page_size": 20, "count": 1, "total_pages": 1}
    result = data["results"][0]
    assert result == {
        "id": str(first.id),
        "nickname": "审核用户",
        "phone_masked": "+86 138****8000",
        "approval_status": "pending",
        "account_status": "active",
        "status_version": 1,
        "approved_at": None,
        "created_at": result["created_at"],
    }
    assert result["created_at"]
    assert first.phone not in response.content.decode()
    assert admin.phone not in response.content.decode()

    detail = client.get(f"/api/v1/admin/users/{first.id}")
    assert detail.status_code == 200
    assert detail.json()["data"]["approval_reason"] is None
    assert "phone" not in detail.json()["data"]


@pytest.mark.django_db
def test_admin_pagination_is_stable_and_bounded():
    admin = create_admin()
    for index in range(3):
        create_user(f"13800138{index:03d}")
    client = authenticated_client(admin)

    first_page = client.get("/api/v1/admin/users", {"page": 1, "page_size": 2})
    second_page = client.get("/api/v1/admin/users", {"page": 2, "page_size": 2})
    oversized = client.get("/api/v1/admin/users", {"page_size": 101})

    expected_ids = list(
        User.objects.filter(is_staff=False)
        .order_by("created_at", "id")
        .values_list("id", flat=True)
    )
    returned_ids = [
        *(item["id"] for item in first_page.json()["data"]["results"]),
        *(item["id"] for item in second_page.json()["data"]["results"]),
    ]
    assert returned_ids == [str(user_id) for user_id in expected_ids]
    assert oversized.status_code == 422


@pytest.mark.django_db
@pytest.mark.parametrize("staff_active", [(False, True), (True, False)])
def test_admin_api_rejects_non_staff_and_inactive_staff(staff_active):
    is_staff, is_active = staff_active
    user = create_user(is_staff=is_staff)
    if not is_active:
        user.is_active = False
        user.account_status = User.AccountStatus.FROZEN
        User.objects.filter(pk=user.pk).update(is_active=False, account_status="frozen")
        user.refresh_from_db()
    response = authenticated_client(user).get("/api/v1/admin/users")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"


@pytest.mark.django_db
def test_review_approve_and_reject_create_append_only_history_and_safe_notification():
    admin = create_admin()
    approved_user = create_user()
    rejected_user = create_user("13700137000")
    client = authenticated_client(admin)

    approved = client.post(
        f"/api/v1/admin/users/{approved_user.id}/review",
        {"decision": "approve"},
        format="json",
    )
    rejected = client.post(
        f"/api/v1/admin/users/{rejected_user.id}/review",
        {
            "decision": "reject",
            "reason": "主体资料不完整",
            "expected_version": rejected_user.status_version,
            "confirmed": True,
        },
        format="json",
    )

    assert approved.status_code == 200
    assert rejected.status_code == 200
    approved_user.refresh_from_db()
    rejected_user.refresh_from_db()
    assert approved_user.approval_status == User.ApprovalStatus.APPROVED
    assert approved_user.approved_at is not None
    assert approved_user.approved_by == admin
    assert approved_user.approval_reason == ""
    assert rejected_user.approval_status == User.ApprovalStatus.REJECTED
    assert rejected_user.approved_at is None
    assert rejected_user.approved_by is None
    assert rejected_user.approval_reason == "主体资料不完整"
    events = UserStatusEvent.objects.order_by("created_at")
    assert [event.event_type for event in events] == ["approved", "rejected"]
    assert all(event.actor == admin for event in events)
    notification = Notification.objects.get(recipient=rejected_user)
    assert notification.title == "审核未通过"
    assert notification.safe_summary == "请查看当前审核状态并完善资料后重新提交。"
    assert notification.notification_type == "approval_rejected"
    assert rejected_user.approval_reason not in notification.safe_summary

    history = client.get(f"/api/v1/admin/users/{rejected_user.id}/history")
    assert history.status_code == 200
    assert history.json()["data"]["results"][0]["reason"] == "主体资料不完整"
    assert client.put(f"/api/v1/admin/users/{rejected_user.id}/history").status_code == 405
    assert client.delete(f"/api/v1/admin/users/{rejected_user.id}/history").status_code == 405


@pytest.mark.django_db
def test_reject_requires_safe_reason_and_repeat_review_conflicts():
    admin = create_admin()
    user = create_user()
    client = authenticated_client(admin)
    path = f"/api/v1/admin/users/{user.id}/review"

    controls = {"expected_version": user.status_version, "confirmed": True}
    missing = client.post(path, {"decision": "reject", **controls}, format="json")
    html = client.post(
        path, {"decision": "reject", "reason": "<b>拒绝</b>", **controls}, format="json"
    )
    first = client.post(path, {"decision": "approve"}, format="json")
    assert missing.json()["error"]["message"] == "拒绝审核时必须填写原因"
    user.refresh_from_db()
    repeat = client.post(
        path,
        {
            "decision": "reject",
            "reason": "重复操作",
            "expected_version": user.status_version,
            "confirmed": True,
        },
        format="json",
    )

    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "APPROVAL_REASON_REQUIRED"
    assert html.status_code == 422
    assert first.status_code == 200
    assert repeat.status_code == 409
    assert repeat.json()["error"]["code"] == "APPROVAL_STATE_CONFLICT"
    assert UserStatusEvent.objects.count() == 1


@pytest.mark.django_db
def test_rejected_user_can_resubmit_with_optional_nickname_and_retains_history():
    admin = create_admin()
    user = create_user()
    admin_client = authenticated_client(admin)
    admin_client.post(
        f"/api/v1/admin/users/{user.id}/review",
        {
            "decision": "reject",
            "reason": "资料需要补充",
            "expected_version": user.status_version,
            "confirmed": True,
        },
        format="json",
    )
    user.refresh_from_db()
    client = authenticated_client(user)

    me = client.get(ME_PATH)
    response = client.post(
        "/api/v1/me/approval/resubmit",
        {"nickname": "  新昵称  "},
        format="json",
    )

    assert me.json()["data"]["approval_reason"] == "资料需要补充"
    assert response.status_code == 200
    assert response.json()["data"]["nickname"] == "新昵称"
    assert "approval_reason" not in response.json()["data"]
    user.refresh_from_db()
    assert user.approval_status == User.ApprovalStatus.PENDING
    assert user.approval_reason == ""
    assert user.phone == "+8613800138000"
    assert set(user.status_events.values_list("event_type", flat=True)) == {
        "rejected",
        "resubmitted",
    }
    assert user.status_events.get(event_type="rejected").reason == "资料需要补充"
    assert user.status_events.get(event_type="resubmitted").actor == user

    rejected_again = create_user("13600136000", approval_status=User.ApprovalStatus.REJECTED)
    rejected_client = authenticated_client(rejected_again)
    phone_change = rejected_client.post(
        "/api/v1/me/approval/resubmit",
        {"phone": "13500135000"},
        format="json",
    )
    assert phone_change.status_code == 422
    rejected_again.refresh_from_db()
    assert rejected_again.phone == "+8613600136000"
    assert rejected_again.approval_status == User.ApprovalStatus.REJECTED


@pytest.mark.django_db
def test_admin_authority_is_rechecked_from_database_before_state_change():
    admin = create_admin()
    target = create_user()
    client = authenticated_client(admin)
    User.objects.filter(pk=admin.pk).update(
        is_active=False,
        account_status=User.AccountStatus.FROZEN,
    )

    response = client.post(
        f"/api/v1/admin/users/{target.id}/review",
        {"decision": "approve"},
        format="json",
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    target.refresh_from_db()
    assert target.approval_status == User.ApprovalStatus.PENDING
    assert target.status_events.count() == 0

    conflict = client.post("/api/v1/me/approval/resubmit", {}, format="json")
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "APPROVAL_STATE_CONFLICT"


@pytest.mark.django_db
def test_staff_and_superuser_cannot_be_business_status_targets():
    actor = create_admin()
    staff = create_admin("13700137000")
    superuser = User.objects.create_superuser(
        phone="13600136000", nickname="超级管理员", password=PASSWORD
    )
    client = authenticated_client(actor)
    for target in (staff, superuser):
        assert (
            client.post(
                f"/api/v1/admin/users/{target.id}/review",
                {"decision": "approve"},
                format="json",
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/api/v1/admin/users/{target.id}/freeze",
                {"expected_version": target.status_version, "confirmed": True},
                format="json",
            ).status_code
            == 404
        )


@pytest.mark.django_db
def test_notifications_are_isolated_and_read_requires_csrf_with_browser_session():
    admin = create_admin()
    first = create_user()
    second = create_user("13700137000")
    admin_client = authenticated_client(admin)
    admin_client.post(
        f"/api/v1/admin/users/{first.id}/review",
        {
            "decision": "reject",
            "reason": "第一位用户原因",
            "expected_version": first.status_version,
            "confirmed": True,
        },
        format="json",
    )
    admin_client.post(
        f"/api/v1/admin/users/{second.id}/review",
        {
            "decision": "reject",
            "reason": "第二位用户原因",
            "expected_version": second.status_version,
            "confirmed": True,
        },
        format="json",
    )
    first_client = browser_client()
    notification = Notification.objects.get(recipient=first)

    listing = first_client.get("/api/v1/notifications")
    missing_csrf = first_client.post(f"/api/v1/notifications/{notification.id}/read", {})
    csrf = first_client.cookies["xianwen_csrf"].value
    read = first_client.post(
        f"/api/v1/notifications/{notification.id}/read",
        {},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )

    other = Notification.objects.get(recipient=second)
    forbidden_other = first_client.post(
        f"/api/v1/notifications/{other.id}/read",
        {},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )

    assert listing.status_code == 200
    assert len(listing.json()["data"]["results"]) == 1
    assert "第一位用户原因" not in listing.content.decode()
    assert "第二位用户原因" not in listing.content.decode()
    assert missing_csrf.status_code == 403
    assert read.status_code == 200
    assert read.json()["data"]["read_at"] is not None
    assert forbidden_other.status_code == 404


@pytest.mark.django_db
def test_admin_and_resubmit_writes_require_real_csrf():
    admin = create_admin()
    target = create_user()
    admin_client = browser_client(admin.phone)
    review_path = f"/api/v1/admin/users/{target.id}/review"

    missing_admin_csrf = admin_client.post(
        review_path,
        {
            "decision": "reject",
            "reason": "需要补充资料",
            "expected_version": target.status_version,
            "confirmed": True,
        },
        format="json",
    )
    admin_csrf = admin_client.cookies["xianwen_csrf"].value
    reviewed = admin_client.post(
        review_path,
        {
            "decision": "reject",
            "reason": "需要补充资料",
            "expected_version": target.status_version,
            "confirmed": True,
        },
        format="json",
        HTTP_X_CSRFTOKEN=admin_csrf,
    )

    assert missing_admin_csrf.status_code == 403
    assert missing_admin_csrf.json()["error"]["code"] == "CSRF_FAILED"
    assert reviewed.status_code == 200

    target.refresh_from_db()
    user_client = browser_client(target.phone)
    missing_user_csrf = user_client.post(
        "/api/v1/me/approval/resubmit",
        {"nickname": "安全重提"},
        format="json",
    )
    user_csrf = user_client.cookies["xianwen_csrf"].value
    resubmitted = user_client.post(
        "/api/v1/me/approval/resubmit",
        {"nickname": "安全重提"},
        format="json",
        HTTP_X_CSRFTOKEN=user_csrf,
    )

    assert missing_user_csrf.status_code == 403
    assert missing_user_csrf.json()["error"]["code"] == "CSRF_FAILED"
    assert resubmitted.status_code == 200


@pytest.mark.django_db
def test_freeze_invalidates_multiple_sessions_and_unfreeze_does_not_restore_them():
    admin = create_admin()
    user = create_user()
    first = browser_client()
    second = browser_client()
    admin_client = authenticated_client(admin)

    frozen = admin_client.post(
        f"/api/v1/admin/users/{user.id}/freeze",
        {"expected_version": user.status_version, "confirmed": True},
        format="json",
    )
    assert frozen.status_code == 200
    assert first.get(ME_PATH).status_code == 401
    assert second.get(ME_PATH).status_code == 401
    user.refresh_from_db()
    assert user.account_status == User.AccountStatus.FROZEN
    assert user.is_active is False
    assert user.session_version == 2
    assert user.approval_status == User.ApprovalStatus.PENDING

    unfrozen = admin_client.post(f"/api/v1/admin/users/{user.id}/unfreeze", {}, format="json")
    assert unfrozen.status_code == 200
    assert first.get(ME_PATH).status_code == 401
    assert second.get(ME_PATH).status_code == 401
    user.refresh_from_db()
    assert user.account_status == User.AccountStatus.ACTIVE
    assert user.is_active is True
    assert user.session_version == 2
    assert browser_client().get(ME_PATH).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("session_value", [None, "1", 0, 2, True])
def test_missing_invalid_or_mismatched_session_version_is_anonymous(session_value):
    create_user()
    client = browser_client()
    session = client.session
    if session_value is None:
        session.pop(SESSION_VERSION_KEY)
    else:
        session[SESSION_VERSION_KEY] = session_value
    session.save()

    assert client.get(ME_PATH).status_code == 401


@pytest.mark.django_db
def test_approved_and_active_permission_matrix():
    permission = ApprovedAndActive()

    class Request:
        pass

    request = Request()
    for approval, account, active, expected in [
        ("approved", "active", True, True),
        ("pending", "active", True, False),
        ("rejected", "active", True, False),
        ("approved", "frozen", False, False),
        ("approved", "cancel_pending", True, False),
    ]:
        request.user = create_user(
            phone=f"1380013{User.objects.count():04d}",
            approval_status=approval,
            account_status=account,
        )
        if request.user.is_active != active:
            request.user.is_active = active
        assert permission.has_permission(request, None) is expected


@pytest.mark.django_db(transaction=True)
def test_concurrent_approve_and_reject_only_one_succeeds():
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL row-lock behavior is verified in Compose and CI.")
    admin = create_admin()
    user = create_user()
    barrier = threading.Barrier(2)
    outcomes = []

    def run(decision, reason):
        close_old_connections()
        barrier.wait()
        try:
            review_user(
                actor_id=admin.id,
                user_id=user.id,
                decision=decision,
                reason=reason,
                request_id="12345678-1234-4234-8234-123456789012",
            )
            outcomes.append("success")
        except ApprovalStateConflict:
            outcomes.append("conflict")
        finally:
            close_old_connections()

    threads = [
        threading.Thread(target=run, args=("approve", "")),
        threading.Thread(target=run, args=("reject", "并发拒绝")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == ["conflict", "success"]
    assert UserStatusEvent.objects.filter(user=user).count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_resubmit_and_review_only_one_succeeds():
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL row-lock behavior is verified in Compose and CI.")
    admin = create_admin()
    user = create_user(approval_status=User.ApprovalStatus.REJECTED)
    barrier = threading.Barrier(2)
    outcomes = []

    def run_resubmit():
        close_old_connections()
        barrier.wait()
        try:
            resubmit_approval(
                user_id=user.id,
                nickname=None,
                request_id="12345678-1234-4234-8234-123456789012",
            )
            outcomes.append("resubmitted")
        finally:
            close_old_connections()

    def run_review():
        close_old_connections()
        barrier.wait()
        try:
            review_user(
                actor_id=admin.id,
                user_id=user.id,
                decision="approve",
                reason="",
                request_id="12345678-1234-4234-8234-123456789012",
            )
            outcomes.append("approved")
        except ApprovalStateConflict:
            outcomes.append("review_conflict")
        finally:
            close_old_connections()

    threads = [threading.Thread(target=run_resubmit), threading.Thread(target=run_review)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert "resubmitted" in outcomes
    assert len(outcomes) == 2


@pytest.mark.django_db(transaction=True)
def test_concurrent_freeze_and_unfreeze_follow_locked_state():
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL row-lock behavior is verified in Compose and CI.")
    admin = create_admin()
    user = create_user()
    barrier = threading.Barrier(2)
    outcomes = []

    def run(action):
        close_old_connections()
        barrier.wait()
        try:
            change_account_status(
                actor_id=admin.id,
                user_id=user.id,
                action=action,
                reason="",
                request_id="12345678-1234-4234-8234-123456789012",
            )
            outcomes.append(f"{action}_success")
        except AccountStateConflict:
            outcomes.append(f"{action}_conflict")
        finally:
            close_old_connections()

    threads = [threading.Thread(target=run, args=(action,)) for action in ("freeze", "unfreeze")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert "freeze_success" in outcomes
    assert len(outcomes) == 2
    user.refresh_from_db()
    if "unfreeze_success" in outcomes:
        assert user.account_status == User.AccountStatus.ACTIVE
        assert user.status_events.count() == 2
    else:
        assert "unfreeze_conflict" in outcomes
        assert user.account_status == User.AccountStatus.FROZEN
        assert user.status_events.count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_freeze_and_login_cannot_leave_a_valid_old_session():
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL row-lock behavior is verified in Compose and CI.")
    admin = create_admin()
    user = create_user()
    barrier = threading.Barrier(2)
    outcomes = []

    def run_login():
        close_old_connections()
        request = RequestFactory().post("/")
        middleware = SessionMiddleware(lambda current_request: None)
        middleware.process_request(request)
        request.session.save()
        barrier.wait()
        try:
            start_browser_session(request, user.id)
            request.session.save()
            outcomes.append(("login_success", request.session[SESSION_VERSION_KEY]))
        except AccountUnavailable:
            outcomes.append(("login_unavailable", None))
        finally:
            close_old_connections()

    def run_freeze():
        close_old_connections()
        barrier.wait()
        change_account_status(
            actor_id=admin.id,
            user_id=user.id,
            action="freeze",
            reason="",
            request_id="12345678-1234-4234-8234-123456789012",
        )
        outcomes.append(("freeze_success", None))
        close_old_connections()

    threads = [threading.Thread(target=run_login), threading.Thread(target=run_freeze)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    user.refresh_from_db()
    assert user.account_status == User.AccountStatus.FROZEN
    assert user.is_active is False
    assert user.session_version == 2
    assert ("freeze_success", None) in outcomes
    successful_login = next(
        (outcome for outcome in outcomes if outcome[0] == "login_success"), None
    )
    if successful_login is not None:
        assert successful_login[1] < user.session_version
    else:
        assert ("login_unavailable", None) in outcomes
