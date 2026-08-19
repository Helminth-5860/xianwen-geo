from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from django_redis import get_redis_connection  # type: ignore[import-untyped]
from redis.exceptions import RedisError

ACQUIRE_SCRIPT = """
local global_key = KEYS[1]
local model_key = KEYS[2]
local now = tonumber(ARGV[1])
local expires = tonumber(ARGV[2])
local global_limit = tonumber(ARGV[3])
local model_limit = tonumber(ARGV[4])
local token = ARGV[5]
redis.call('ZREMRANGEBYSCORE', global_key, '-inf', now)
redis.call('ZREMRANGEBYSCORE', model_key, '-inf', now)
if redis.call('ZCARD', global_key) >= global_limit then return 0 end
if redis.call('ZCARD', model_key) >= model_limit then return 0 end
redis.call('ZADD', global_key, expires, token)
redis.call('ZADD', model_key, expires, token)
return 1
"""

RELEASE_SCRIPT = """
redis.call('ZREM', KEYS[1], ARGV[1])
redis.call('ZREM', KEYS[2], ARGV[1])
return 1
"""


class DetectionSemaphoreUnavailable(Exception):
    pass


@dataclass(frozen=True)
class DetectionSemaphoreLease:
    token: str
    global_key: str
    model_key: str


class DetectionSemaphoreStore:
    def __init__(self, client=None):
        self.client = client or get_redis_connection("default")

    def acquire(
        self,
        *,
        model_key: str,
        global_limit: int,
        model_limit: int,
        lease_seconds: int,
    ) -> DetectionSemaphoreLease | None:
        if global_limit < 1 or model_limit < 1 or lease_seconds < 1:
            raise ValueError("Invalid detection semaphore limit.")
        token = str(uuid.uuid4())
        now = int(time.time())
        expires = now + lease_seconds
        global_key = "geo:semaphore:global:v1"
        scoped_model_key = f"geo:semaphore:model:v1:{model_key}"
        try:
            acquired = self.client.eval(
                ACQUIRE_SCRIPT,
                2,
                global_key,
                scoped_model_key,
                now,
                expires,
                global_limit,
                model_limit,
                token,
            )
        except RedisError as exc:
            raise DetectionSemaphoreUnavailable from exc
        if int(acquired) != 1:
            return None
        return DetectionSemaphoreLease(token, global_key, scoped_model_key)

    def release(self, lease: DetectionSemaphoreLease) -> None:
        try:
            self.client.eval(
                RELEASE_SCRIPT,
                2,
                lease.global_key,
                lease.model_key,
                lease.token,
            )
        except RedisError as exc:
            raise DetectionSemaphoreUnavailable from exc
