from __future__ import annotations

import uuid
from unittest.mock import Mock, patch

import pytest
from celery.exceptions import Retry
from django.db import OperationalError
from django.test import override_settings

from apps.geo.semaphores import DetectionDispatchLease, DetectionDispatchLeaseStore
from apps.geo.tasks import (
    dispatch_model_calls_task,
    execute_model_call_task,
    execute_semantic_score_task,
    prepare_report_task,
)


def test_dispatch_lease_uses_atomic_set_nx_and_token_checked_release():
    client = Mock()
    client.set.return_value = True
    store = DetectionDispatchLeaseStore(client=client)

    lease = store.acquire(call_id="call-1", lease_seconds=960)

    assert lease is not None
    assert lease.key == "geo:dispatch:model-call:v1:call-1"
    client.set.assert_called_once_with(lease.key, lease.token, nx=True, ex=960)

    store.release(lease)
    client.eval.assert_called_once()
    assert client.eval.call_args.args[1:] == (1, lease.key, lease.token)


@override_settings(GEO_DETECTION_DISPATCH_BATCH=100, GEO_DETECTION_QUEUE_TIMEOUT_SECONDS=900)
def test_dispatcher_publishes_each_call_once_while_lease_is_held():
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    first_lease = DetectionDispatchLease(token="dispatch-token", key=f"key:{first_id}")
    store = Mock()
    store.acquire.side_effect = [first_lease, None]

    with (
        patch("apps.geo.tasks.expire_queue_timeouts", return_value=0),
        patch("apps.geo.tasks.expire_stale_running_calls", return_value=0),
        patch("apps.geo.tasks.due_model_call_ids", return_value=[first_id, second_id]),
        patch("apps.geo.tasks.DetectionDispatchLeaseStore", return_value=store),
        patch.object(execute_model_call_task, "apply_async") as apply_async,
    ):
        result = dispatch_model_calls_task.run()

    apply_async.assert_called_once()
    assert apply_async.call_args.kwargs["args"] == [str(first_id), first_lease.token]
    assert apply_async.call_args.kwargs["queue"] == "geo_detection"
    assert result == {
        "queued": 1,
        "deduplicated": 1,
        "enqueue_failures": 0,
        "queue_timeouts": 0,
        "stale_failed": 0,
    }


@override_settings(GEO_DETECTION_DISPATCH_BATCH=100, GEO_DETECTION_QUEUE_TIMEOUT_SECONDS=900)
def test_dispatcher_releases_lease_when_broker_publish_fails():
    call_id = uuid.uuid4()
    lease = DetectionDispatchLease(token="dispatch-token", key=f"key:{call_id}")
    store = Mock()
    store.acquire.return_value = lease

    with (
        patch("apps.geo.tasks.expire_queue_timeouts", return_value=0),
        patch("apps.geo.tasks.expire_stale_running_calls", return_value=0),
        patch("apps.geo.tasks.due_model_call_ids", return_value=[call_id]),
        patch("apps.geo.tasks.DetectionDispatchLeaseStore", return_value=store),
        patch.object(execute_model_call_task, "apply_async", side_effect=RuntimeError("broker")),
    ):
        result = dispatch_model_calls_task.run()

    store.release.assert_called_once_with(lease)
    assert result["queued"] == 0
    assert result["enqueue_failures"] == 1


def test_worker_releases_dispatch_lease_and_accepts_legacy_one_argument_message():
    store = Mock()
    with (
        patch("apps.geo.tasks.execute_model_call", return_value={"status": "queued"}),
        patch("apps.geo.tasks.DetectionDispatchLeaseStore", return_value=store) as store_factory,
    ):
        assert execute_model_call_task.run("call-1", "dispatch-token") == {"status": "queued"}
        assert execute_model_call_task.run("legacy-call") == {"status": "queued"}

    store.release.assert_called_once_with(
        DetectionDispatchLease(
            token="dispatch-token",
            key="geo:dispatch:model-call:v1:call-1",
        )
    )
    store_factory.assert_called_once_with()


def test_legacy_duplicate_terminal_message_does_not_enqueue_downstream_work():
    with (
        patch(
            "apps.geo.tasks.execute_model_call",
            return_value={"status": "succeeded", "terminal_transition": False},
        ),
        patch.object(execute_semantic_score_task, "apply_async") as semantic_apply,
        patch.object(prepare_report_task, "apply_async") as report_apply,
    ):
        result = execute_model_call_task.run("legacy-terminal-call")

    assert result == {"status": "succeeded", "terminal_transition": False}
    semantic_apply.assert_not_called()
    report_apply.assert_not_called()


def test_internal_retry_keeps_dispatch_token_and_lease_until_retry_finishes():
    with (
        patch("apps.geo.tasks.execute_model_call", side_effect=OperationalError("database")),
        patch.object(execute_model_call_task, "retry", side_effect=Retry()) as retry,
        patch("apps.geo.tasks._release_dispatch_lease") as release,
        pytest.raises(Retry),
    ):
        execute_model_call_task.run("call-1", "dispatch-token")

    assert retry.call_args.kwargs["args"] == ["call-1", "dispatch-token"]
    release.assert_not_called()


def test_internal_terminal_failure_enqueues_report_preparation_once():
    call = Mock(job_id=uuid.uuid4())
    manager = Mock()
    manager.select_related.return_value.filter.return_value.first.return_value = call
    terminal_result = {"status": "failed", "terminal_transition": True}

    with (
        patch("apps.geo.tasks.execute_model_call", side_effect=RuntimeError("worker")),
        patch("apps.geo.tasks.fail_internal_model_call", return_value=terminal_result),
        patch("apps.geo.tasks.ModelCall.objects", manager),
        patch.object(execute_semantic_score_task, "apply_async") as semantic_apply,
        patch.object(prepare_report_task, "apply_async") as report_apply,
    ):
        result = execute_model_call_task.run("call-1")

    assert result == terminal_result
    semantic_apply.assert_not_called()
    report_apply.assert_called_once_with(args=[str(call.job_id)], queue="system_tasks")
