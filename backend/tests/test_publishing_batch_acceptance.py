from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.publishing.management.commands import accept_publishing_platforms as acceptance


def _subject():
    return SimpleNamespace(id="subject-1", user_id="user-1")


def _article():
    return SimpleNamespace(
        id="article-1",
        title="统一验收测试文章",
        content="这是一篇用于验证批量草稿保存能力的文章。",
        moderation_status="passed",
    )


def _account(key: str):
    return SimpleNamespace(platform_key=key, session_expires_at=None)


def _prepare_command(monkeypatch, accounts):
    command = acceptance.Command
    monkeypatch.setattr(command, "_subject", lambda self, value: _subject())
    monkeypatch.setattr(command, "_article", lambda self, subject, value: _article())
    monkeypatch.setattr(command, "_account_map", lambda self, subject: accounts)
    monkeypatch.setattr(command, "_safe_assets", lambda self, subject, article: ())
    monkeypatch.setattr(
        acceptance,
        "platform_credentials",
        lambda account: {"cookies": [{"name": "session", "value": "hidden"}]},
    )


def test_command_runs_connected_platforms_in_one_draft_batch(monkeypatch):
    _prepare_command(
        monkeypatch,
        {"zhihu": _account("zhihu"), "weibo": _account("weibo")},
    )
    calls = []

    def worker(**kwargs):
        calls.append(kwargs)
        return {"success": True, "status": "drafted"}

    monkeypatch.setattr(acceptance, "publish_to_platform", worker)
    output = io.StringIO()

    call_command(
        "accept_publishing_platforms",
        "--platforms",
        "zhihu",
        "weibo",
        stdout=output,
    )

    assert {item["platform_key"] for item in calls} == {"zhihu", "weibo"}
    assert all(item["publish_mode"] == "draft" for item in calls)
    assert all(item["target_id"] for item in calls)
    assert all(item["title"].startswith("【验") for item in calls)
    assert "通过 2 个" in output.getvalue()
    assert "hidden" not in output.getvalue()


def test_command_reports_unlinked_platforms_without_calling_worker(monkeypatch):
    _prepare_command(monkeypatch, {"zhihu": _account("zhihu")})
    calls = []
    monkeypatch.setattr(
        acceptance,
        "publish_to_platform",
        lambda **kwargs: calls.append(kwargs) or {"success": True, "status": "drafted"},
    )
    output = io.StringIO()

    with pytest.raises(CommandError, match="尚未完成"):
        call_command(
            "accept_publishing_platforms",
            "--platforms",
            "zhihu",
            "weibo",
            stdout=output,
        )

    assert len(calls) == 1
    assert calls[0]["platform_key"] == "zhihu"
    assert "微博：已跳过，尚未授权，已跳过" in output.getvalue()


def test_public_publish_requires_exact_chinese_confirmation(monkeypatch):
    _prepare_command(monkeypatch, {"zhihu": _account("zhihu")})
    called = False

    def worker(**kwargs):
        nonlocal called
        called = True
        return {
            "success": True,
            "status": "published",
            "publicUrl": "https://example.com/article/acceptance",
        }

    monkeypatch.setattr(acceptance, "publish_to_platform", worker)

    with pytest.raises(CommandError, match="必须同时填写"):
        call_command(
            "accept_publishing_platforms",
            "--platforms",
            "zhihu",
            "--public",
            "--confirm-public",
            "确认",
        )
    assert called is False

    output = io.StringIO()
    call_command(
        "accept_publishing_platforms",
        "--platforms",
        "zhihu",
        "--public",
        "--confirm-public",
        acceptance.PUBLIC_CONFIRMATION,
        stdout=output,
    )
    assert called is True
    assert "公开发布结果已确认" in output.getvalue()


def test_public_submission_without_public_result_is_not_accepted(monkeypatch):
    case = acceptance.AcceptanceCase(
        platform_key="zhihu",
        platform_name="知乎",
        title="公开验收测试",
        content_html="<p>公开验收测试</p>",
        content_text="公开验收测试",
        summary="公开验收测试",
        assets=(),
        credentials={"token": "hidden"},
    )
    monkeypatch.setattr(
        acceptance,
        "publish_to_platform",
        lambda **kwargs: {"success": True, "status": "submitted"},
    )
    monkeypatch.setattr(acceptance, "close_old_connections", lambda: None)

    result = acceptance._execute_case(case, "public")

    assert result.outcome == "failed"
    assert "尚未取得" in result.message


def test_public_publish_requires_article_to_pass_content_check(monkeypatch):
    _prepare_command(monkeypatch, {"zhihu": _account("zhihu")})
    unchecked = _article()
    unchecked.moderation_status = "not_checked"
    monkeypatch.setattr(
        acceptance.Command,
        "_article",
        lambda self, subject, value: unchecked,
    )
    called = False

    def worker(**kwargs):
        nonlocal called
        called = True
        return {"success": True, "status": "published"}

    monkeypatch.setattr(acceptance, "publish_to_platform", worker)

    with pytest.raises(CommandError, match="已通过内容检查"):
        call_command(
            "accept_publishing_platforms",
            "--platforms",
            "zhihu",
            "--public",
            "--confirm-public",
            acceptance.PUBLIC_CONFIRMATION,
        )
    assert called is False


def test_image_required_platform_fails_closed_without_approved_asset(monkeypatch):
    _prepare_command(monkeypatch, {"xiaohongshu": _account("xiaohongshu")})
    called = False

    def worker(**kwargs):
        nonlocal called
        called = True
        return {"success": True, "status": "drafted"}

    monkeypatch.setattr(acceptance, "publish_to_platform", worker)
    output = io.StringIO()

    with pytest.raises(CommandError, match="未通过或尚未完成"):
        call_command(
            "accept_publishing_platforms",
            "--platforms",
            "xiaohongshu",
            stdout=output,
        )

    assert called is False
    assert "缺少已审核的有效图片" in output.getvalue()


def test_concurrency_is_bounded_and_credentials_never_appear_in_result(monkeypatch):
    assert acceptance._bounded_concurrency(0) == 1
    assert acceptance._bounded_concurrency(3) == 3
    assert acceptance._bounded_concurrency(99) == 4

    case = acceptance.AcceptanceCase(
        platform_key="zhihu",
        platform_name="知乎",
        title="测试",
        content_html="<p>测试</p>",
        content_text="测试",
        summary="测试",
        assets=(),
        credentials={"token": "top-secret"},
    )
    monkeypatch.setattr(
        acceptance,
        "publish_to_platform",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("top-secret")),
    )
    monkeypatch.setattr(acceptance, "close_old_connections", lambda: None)

    result = acceptance._execute_case(case, "draft")

    assert result.outcome == "failed"
    assert "top-secret" not in repr(case)
    assert "top-secret" not in result.message


def test_public_failure_is_never_retried(monkeypatch):
    calls = 0
    case = acceptance.AcceptanceCase(
        platform_key="zhihu",
        platform_name="知乎",
        title="公开验收测试",
        content_html="<p>公开验收测试</p>",
        content_text="公开验收测试",
        summary="公开验收测试",
        assets=(),
        credentials={"token": "hidden"},
    )

    def worker(**kwargs):
        nonlocal calls
        calls += 1
        raise acceptance.PublishingWorkerError("worker_unavailable")

    monkeypatch.setattr(acceptance, "publish_to_platform", worker)
    monkeypatch.setattr(acceptance, "close_old_connections", lambda: None)

    result = acceptance._execute_case(case, "public")

    assert calls == 1
    assert result.outcome == "failed"
