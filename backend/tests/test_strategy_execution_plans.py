from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from rest_framework.test import APIClient

from apps.geo.execution_plans import _strategy_matching_facts
from apps.geo.models import StrategyExecutionPlan
from apps.media_inquiries.models import PaidMediaInquiry
from apps.users.models import User
from tests.test_geo_strategy_assistant import (
    _ContentAdapter,
    _create_strategy,
    _execute_strategy,
)
from tests.test_geo_strategy_assistant import (
    stage_facts as _strategy_stage_facts_fixture,
)
from tests.test_paid_media_inquiries import media_catalog as _paid_media_catalog_fixture

pytestmark = pytest.mark.django_db


@pytest.fixture
def strategy_stage_facts(monkeypatch):
    return _strategy_stage_facts_fixture.__wrapped__(monkeypatch)


@pytest.fixture
def paid_media_catalog(tmp_path, settings):
    yield from _paid_media_catalog_fixture.__wrapped__(tmp_path, settings)


@pytest.fixture
def execution_facts(strategy_stage_facts):
    user, subject, _, runtime, *_ = strategy_stage_facts
    adapter = _ContentAdapter()
    strategy, created = _create_strategy(strategy_stage_facts, adapter)
    assert created is True
    assert _execute_strategy(strategy, runtime, adapter) == {"status": "succeeded"}
    strategy.refresh_from_db()
    return user, subject, strategy


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def _data(response):
    return response.json()["data"]


def _preview(client, strategy):
    return client.get(f"/api/v1/strategies/{strategy.pk}/execution-preview")


def _create_plan(
    client,
    strategy,
    *,
    package_code="basic",
    item_keys=None,
    media_ids=None,
    key="execution-plan-create-0001",
):
    selected_item_keys = ["priority-01", "article-01", "retest"] if item_keys is None else item_keys
    return client.post(
        f"/api/v1/strategies/{strategy.pk}/execution-plans",
        {
            "package_code": package_code,
            "item_keys": selected_item_keys,
            "media_ids": media_ids or [],
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
    )


def _patch_plan(client, plan, *, action, item_key=None):
    body = {"action": action, "expected_version": plan["version"]}
    if item_key is not None:
        body["item_key"] = item_key
    return client.patch(
        f"/api/v1/execution-plans/{plan['id']}",
        body,
        format="json",
    )


def test_execution_preview_is_stable_truthful_and_matches_frontend_contract(
    execution_facts,
    paid_media_catalog,
):
    user, _subject, strategy = execution_facts
    client = _client(user)

    first = _preview(client, strategy)
    second = _preview(client, strategy)

    assert first.status_code == second.status_code == 200
    first_payload = _data(first)
    second_payload = _data(second)
    assert set(first_payload) == {"preview", "plan"}
    assert first_payload["plan"] is None
    assert [item["key"] for item in first_payload["preview"]["items"]] == [
        item["key"] for item in second_payload["preview"]["items"]
    ]

    items = first_payload["preview"]["items"]
    assert {item["kind"] for item in items} <= {
        "self_service",
        "platform_assisted",
        "manual_service",
        "paid_media",
    }
    assert all(
        {
            "key",
            "title",
            "problem",
            "reason",
            "recommendation",
            "deliverables",
            "success_metric",
            "expected_improvement",
            "priority",
            "kind",
            "estimated_days",
            "estimated_price_cents",
            "cost_note",
            "selected_by_default",
        }
        <= set(item)
        for item in items
    )
    priority_item = next(item for item in items if item["key"] == "priority-01")
    assert priority_item["route"] == f"/geo/strategy/{strategy.report_id}"
    assert [package["code"] for package in first_payload["preview"]["packages"]] == [
        "basic",
        "focused",
        "comprehensive",
        "custom",
    ]

    media = first_payload["preview"]["recommended_media"]
    assert 1 <= len(media) <= 6
    assert all(item["url"] and item["price_cents"] > 0 for item in media)
    assert all("确认" in item["reason"] for item in media)
    assert all(item["selected_by_default"] is False for item in media)
    assert all(package["media_ids"] == [] for package in first_payload["preview"]["packages"])


def test_media_matching_uses_subject_industry_and_does_not_treat_geo_score_as_it():
    matched = SimpleNamespace(
        report_facts={
            "subject": {
                "official_name": "广州新能源汽车服务企业",
                "fields": {"service_area": [{"name": "广东省广州市"}]},
            },
            "scores": {"geo": 80},
        }
    )
    categories, regions = _strategy_matching_facts(matched)
    assert "汽车行业" in categories
    assert "广东" in regions
    assert "IT科技" not in categories

    generic = SimpleNamespace(
        report_facts={"subject": {"official_name": "示例企业"}, "scores": {"geo": 80}}
    )
    categories, _regions = _strategy_matching_facts(generic)
    assert "IT科技" not in categories


def test_create_plan_uses_server_media_price_and_is_idempotent(
    execution_facts,
    paid_media_catalog,
):
    user, _subject, strategy = execution_facts
    client = _client(user)

    created = _create_plan(client, strategy, item_keys=[], media_ids=["media-one"])
    assert created.status_code == 201
    plan = _data(created)
    assert plan["replayed"] is False
    assert plan["package_code"] == "custom"
    assert plan["package_name"] == "自定义"
    assert plan["estimated_price_cents"] == 12345
    assert plan["selected_media"] == [
        {
            "id": "media-one",
            "name": "人民媒体",
            "url": "https://news.example.cn/article/1",
            "domain": "news.example.cn",
            "logo_path": "/paid-media-logos/one.png",
            "price_cents": 12345,
            "inquiry_status": "pending",
        }
    ]
    assert [item["key"] for item in plan["items"]] == ["paid-media"]
    assert plan["items"][0]["cost_note"] == "以管理员确认的最终报价为准。"
    inquiry = PaidMediaInquiry.objects.get()
    assert inquiry.total_price == Decimal("123.45")

    replay = _create_plan(client, strategy, item_keys=[], media_ids=["media-one"])
    assert replay.status_code == 200
    assert _data(replay)["id"] == plan["id"]
    assert _data(replay)["replayed"] is True
    assert StrategyExecutionPlan.objects.count() == 1
    assert PaidMediaInquiry.objects.count() == 1

    conflict = _create_plan(
        client,
        strategy,
        package_code="custom",
        item_keys=["retest"],
        key="execution-plan-create-0002",
    )
    assert conflict.status_code == 409
    assert "已经建立" in conflict.json()["error"]["message"]


def test_execution_item_state_flow_and_optimistic_version(execution_facts):
    user, _subject, strategy = execution_facts
    client = _client(user)
    created = _create_plan(client, strategy)
    assert created.status_code == 201
    plan = _data(created)
    item_keys = [item["key"] for item in plan["items"]]

    stale_version = plan["version"]
    started = _patch_plan(client, plan, action="start_item", item_key=item_keys[0])
    assert started.status_code == 200
    plan = _data(started)
    assert plan["items"][0]["status"] == "in_progress"

    stale = client.patch(
        f"/api/v1/execution-plans/{plan['id']}",
        {
            "action": "complete_item",
            "item_key": item_keys[0],
            "expected_version": stale_version,
        },
        format="json",
    )
    assert stale.status_code == 409
    assert "刷新" in stale.json()["error"]["message"]

    completed = _patch_plan(client, plan, action="complete_item", item_key=item_keys[0])
    assert completed.status_code == 200
    plan = _data(completed)

    cancelled = _patch_plan(client, plan, action="cancel_item", item_key=item_keys[1])
    assert cancelled.status_code == 200
    plan = _data(cancelled)
    second_item = next(item for item in plan["items"] if item["key"] == item_keys[1])
    assert second_item["status"] == "cancelled"

    restored = _patch_plan(client, plan, action="restore_item", item_key=item_keys[1])
    assert restored.status_code == 200
    plan = _data(restored)

    for item in plan["items"]:
        if item["status"] == "pending":
            response = _patch_plan(client, plan, action="complete_item", item_key=item["key"])
            assert response.status_code == 200
            plan = _data(response)
    assert plan["status"] == "completed"
    assert all(item["status"] == "completed" for item in plan["items"])

    cancel_completed = _patch_plan(client, plan, action="cancel_plan")
    assert cancel_completed.status_code == 409
    assert "已完成" in cancel_completed.json()["error"]["message"]


def test_cancelling_paid_media_item_cancels_only_pending_inquiry(
    execution_facts,
    paid_media_catalog,
):
    user, _subject, strategy = execution_facts
    client = _client(user)
    created = _create_plan(client, strategy, media_ids=["media-two"])
    plan = _data(created)

    inquiry = PaidMediaInquiry.objects.get()
    PaidMediaInquiry.objects.filter(pk=inquiry.pk).update(status=PaidMediaInquiry.Status.CONTACTED)
    blocked = _patch_plan(client, plan, action="cancel_item", item_key="paid-media")
    assert blocked.status_code == 409
    assert "联系管理员" in blocked.json()["error"]["message"]
    PaidMediaInquiry.objects.filter(pk=inquiry.pk).update(status=PaidMediaInquiry.Status.PENDING)

    cancelled = _patch_plan(client, plan, action="cancel_item", item_key="paid-media")
    assert cancelled.status_code == 200
    plan = _data(cancelled)
    media_item = next(item for item in plan["items"] if item["key"] == "paid-media")
    assert media_item["status"] == "cancelled"
    inquiry.refresh_from_db()
    assert inquiry.status == PaidMediaInquiry.Status.CANCELLED
    assert plan["selected_media"][0]["inquiry_status"] == "cancelled"

    restore = _patch_plan(client, plan, action="restore_item", item_key="paid-media")
    assert restore.status_code == 409
    assert "不能直接恢复" in restore.json()["error"]["message"]

    cancelled_plan = _patch_plan(client, plan, action="cancel_plan")
    assert cancelled_plan.status_code == 200
    assert _data(cancelled_plan)["status"] == "cancelled"


def test_admin_cancelled_media_can_be_closed_by_user(
    execution_facts,
    paid_media_catalog,
):
    user, _subject, strategy = execution_facts
    client = _client(user)
    created = _create_plan(
        client,
        strategy,
        item_keys=[],
        media_ids=["media-two"],
    )
    plan = _data(created)
    inquiry = PaidMediaInquiry.objects.get()
    PaidMediaInquiry.objects.filter(pk=inquiry.pk).update(status=PaidMediaInquiry.Status.CANCELLED)

    cancelled = _patch_plan(client, plan, action="cancel_item", item_key="paid-media")
    assert cancelled.status_code == 200
    payload = _data(cancelled)
    assert payload["status"] == "cancelled"
    assert payload["items"][0]["status"] == "cancelled"
    assert payload["selected_media"][0]["inquiry_status"] == "cancelled"


def test_execution_plan_endpoints_fail_closed_across_users_and_subjects(
    execution_facts,
    paid_media_catalog,
):
    owner, subject, strategy = execution_facts
    owner_client = _client(owner)
    plan = _data(_create_plan(owner_client, strategy))

    outsider = User.objects.create_user(
        phone=f"137{uuid.uuid4().int % 100000000:08d}",
        nickname="其他用户",
        password="Other-user-password-2026!",
        account_status=User.AccountStatus.ACTIVE,
    )
    outsider_client = _client(outsider)
    assert _preview(outsider_client, strategy).status_code == 404
    assert outsider_client.get(f"/api/v1/execution-plans/{plan['id']}").status_code == 404
    assert outsider_client.get(f"/api/v1/subjects/{subject.pk}/execution-plans").status_code == 404
    assert (
        outsider_client.patch(
            f"/api/v1/execution-plans/{plan['id']}",
            {
                "action": "start_item",
                "item_key": plan["items"][0]["key"],
                "expected_version": plan["version"],
            },
            format="json",
        ).status_code
        == 404
    )


def test_execution_plan_list_is_paginated_at_twenty(execution_facts):
    user, subject, strategy = execution_facts
    client = _client(user)
    _create_plan(client, strategy)

    listed = client.get(f"/api/v1/subjects/{subject.pk}/execution-plans")
    assert listed.status_code == 200
    payload = _data(listed)
    assert payload["pagination"] == {
        "page": 1,
        "page_size": 20,
        "count": 1,
        "total_pages": 1,
    }

    too_many = client.get(
        f"/api/v1/subjects/{subject.pk}/execution-plans",
        {"page_size": 21},
    )
    assert too_many.status_code == 422
    assert "最多显示 20 条" in too_many.json()["error"]["message"]
