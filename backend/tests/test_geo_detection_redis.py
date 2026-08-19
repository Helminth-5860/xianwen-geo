from __future__ import annotations

import os

import pytest
import redis

from apps.geo.semaphores import DetectionSemaphoreStore

pytestmark = pytest.mark.skipif(not os.getenv("REDIS_URL"), reason="requires isolated Redis")


def test_real_redis_global_and_model_semaphores_are_bounded_and_releasable():
    client = redis.Redis.from_url(os.environ["REDIS_URL"])
    client.delete("geo:semaphore:global:v1", "geo:semaphore:model:v1:deepseek")
    store = DetectionSemaphoreStore(client=client)
    first = store.acquire(model_key="deepseek", global_limit=1, model_limit=1, lease_seconds=30)
    assert first is not None
    assert (
        store.acquire(model_key="deepseek", global_limit=1, model_limit=1, lease_seconds=30) is None
    )
    store.release(first)
    second = store.acquire(model_key="deepseek", global_limit=1, model_limit=1, lease_seconds=30)
    assert second is not None
    store.release(second)
