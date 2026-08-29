from __future__ import annotations

import pytest
from django.test import override_settings

from apps.publishing.authorization import begin_browser_authorization
from apps.publishing.models import PlatformAuthorizationSession
from apps.publishing.services import PublishingInputError, create_authorization_session
from apps.subjects.models import Subject, SubjectType
from apps.users.models import User


def _user_and_subjects():
    user = User.objects.create_user(
        phone="13900000081",
        nickname="授权并发保护测试",
        password="test-password",
    )
    subject_type = SubjectType.objects.create(key="publishing-auth-test", name="授权测试")
    subjects = [
        Subject.objects.create(
            user=user,
            subject_type=subject_type,
            status=Subject.Status.ACTIVE,
            schema_version=1,
            schema_snapshot={},
            schema_digest=f"schema-digest-{index}",
        )
        for index in range(2)
    ]
    return user, subjects


def _enable_internal_authorization(monkeypatch):
    monkeypatch.setattr(
        "apps.publishing.services.platform_for_user",
        lambda **kwargs: {
            "key": kwargs["platform_key"],
            "authorization_enabled": True,
            "can_enable_auto": False,
            "availability_message": "",
        },
    )


@pytest.mark.django_db
def test_repeated_authorization_start_reuses_session_and_launches_one_browser(monkeypatch):
    user, subjects = _user_and_subjects()
    _enable_internal_authorization(monkeypatch)
    starts: list[str] = []

    def fake_start(*, session_id, platform_key, expires_at):
        starts.append(session_id)
        return {
            "remote_session_ref": f"remote-{session_id}",
            "action_url": "http://127.0.0.1:8092/v1/authorization/session",
        }

    monkeypatch.setattr("apps.publishing.authorization.start_authorization_session", fake_start)
    monkeypatch.setattr(
        "apps.publishing.tasks.sync_authorization_session_task.delay",
        lambda _session_id: None,
    )

    first = begin_browser_authorization(
        user=user,
        subject_id=subjects[0].id,
        platform_key="zhihu",
    )
    second = begin_browser_authorization(
        user=user,
        subject_id=subjects[0].id,
        platform_key="zhihu",
    )

    assert second.pk == first.pk
    assert starts == [str(first.pk)]
    assert PlatformAuthorizationSession.objects.filter(user=user, platform_key="zhihu").count() == 1


@pytest.mark.django_db
def test_same_platform_cannot_open_another_subject_authorization_window(monkeypatch):
    user, subjects = _user_and_subjects()
    _enable_internal_authorization(monkeypatch)
    create_authorization_session(user=user, subject_id=subjects[0].id, platform_key="zhihu")

    with pytest.raises(PublishingInputError, match="已有授权窗口"):
        create_authorization_session(user=user, subject_id=subjects[1].id, platform_key="zhihu")

    assert PlatformAuthorizationSession.objects.filter(user=user, platform_key="zhihu").count() == 1


@pytest.mark.django_db
@override_settings(
    PUBLISHING_AUTH_MAX_ACTIVE_SESSIONS_PER_USER=2,
    PUBLISHING_AUTH_START_RATE_LIMIT=10,
    PUBLISHING_AUTH_START_RATE_WINDOW_SECONDS=60,
)
def test_active_authorization_session_limit_is_enforced_across_platforms(monkeypatch):
    user, subjects = _user_and_subjects()
    _enable_internal_authorization(monkeypatch)
    create_authorization_session(user=user, subject_id=subjects[0].id, platform_key="zhihu")
    create_authorization_session(user=user, subject_id=subjects[0].id, platform_key="weibo")

    with pytest.raises(PublishingInputError, match="授权窗口较多"):
        create_authorization_session(user=user, subject_id=subjects[0].id, platform_key="toutiao")

    assert PlatformAuthorizationSession.objects.filter(user=user).count() == 2


@pytest.mark.django_db
@override_settings(
    PUBLISHING_AUTH_MAX_ACTIVE_SESSIONS_PER_USER=10,
    PUBLISHING_AUTH_START_RATE_LIMIT=2,
    PUBLISHING_AUTH_START_RATE_WINDOW_SECONDS=60,
)
def test_authorization_start_rate_limit_counts_recent_terminal_sessions(monkeypatch):
    user, subjects = _user_and_subjects()
    _enable_internal_authorization(monkeypatch)
    first, _ = create_authorization_session(
        user=user,
        subject_id=subjects[0].id,
        platform_key="zhihu",
    )
    first.status = PlatformAuthorizationSession.Status.FAILED
    first.save(update_fields=("status", "updated_at"))
    second, _ = create_authorization_session(
        user=user,
        subject_id=subjects[0].id,
        platform_key="weibo",
    )
    second.status = PlatformAuthorizationSession.Status.FAILED
    second.save(update_fields=("status", "updated_at"))

    with pytest.raises(PublishingInputError, match="操作过于频繁"):
        create_authorization_session(user=user, subject_id=subjects[0].id, platform_key="toutiao")

    assert PlatformAuthorizationSession.objects.filter(user=user).count() == 2
