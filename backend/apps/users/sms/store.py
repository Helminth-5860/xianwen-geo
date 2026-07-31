from dataclasses import dataclass
from typing import Protocol

from django.conf import settings
from django_redis import get_redis_connection  # type: ignore[import-untyped]
from redis.exceptions import NoScriptError, RedisError

from .exceptions import SmsRateLimited, SmsServiceUnavailable
from .purposes import SmsPurpose

RESERVE_SCRIPT = """
local code_key = KEYS[1]
local cooldown_key = KEYS[2]
local phone_limit_key = KEYS[3]
local ip_limit_key = KEYS[4]
local combination_limit_key = KEYS[5]

if redis.call("EXISTS", cooldown_key) == 1 then
  return "rate_limited"
end

local limits = {
  {phone_limit_key, tonumber(ARGV[5]), tonumber(ARGV[6])},
  {ip_limit_key, tonumber(ARGV[7]), tonumber(ARGV[8])},
  {combination_limit_key, tonumber(ARGV[9]), tonumber(ARGV[10])}
}
for _, item in ipairs(limits) do
  local current = tonumber(redis.call("GET", item[1]) or "0")
  if current >= item[2] then
    return "rate_limited"
  end
end

for _, item in ipairs(limits) do
  local count = redis.call("INCR", item[1])
  if count == 1 then
    redis.call("EXPIRE", item[1], item[3])
  end
end

redis.call("SET", cooldown_key, "1", "EX", tonumber(ARGV[4]))
redis.call(
  "HSET",
  code_key,
  "generation_id", ARGV[1],
  "code_digest", ARGV[2],
  "state", "pending",
  "attempts", "0"
)
redis.call("EXPIRE", code_key, tonumber(ARGV[3]))
return "reserved"
"""

ACTIVATE_SCRIPT = """
if redis.call("HGET", KEYS[1], "generation_id") ~= ARGV[1] then
  return "stale"
end
if redis.call("HGET", KEYS[1], "state") ~= "pending" then
  return "stale"
end
redis.call("HSET", KEYS[1], "state", "active")
return "activated"
"""

INVALIDATE_SCRIPT = """
if redis.call("HGET", KEYS[1], "generation_id") == ARGV[1] then
  redis.call("DEL", KEYS[1])
  return "invalidated"
end
return "stale"
"""

VERIFY_SCRIPT = """
if redis.call("HGET", KEYS[1], "generation_id") ~= ARGV[1] then
  return "invalid"
end
if redis.call("HGET", KEYS[1], "state") ~= "active" then
  return "invalid"
end
if redis.call("HGET", KEYS[1], "code_digest") == ARGV[2] then
  redis.call("DEL", KEYS[1])
  return "consumed"
end
local attempts = redis.call("HINCRBY", KEYS[1], "attempts", 1)
if attempts >= tonumber(ARGV[3]) then
  redis.call("DEL", KEYS[1])
  return "invalidated"
end
return "invalid"
"""


@dataclass(frozen=True)
class SmsRedisKeys:
    code: str
    cooldown: str
    phone_limit: str
    ip_limit: str
    combination_limit: str


class SmsVerificationStore(Protocol):
    def reserve(self, keys: SmsRedisKeys, generation_id: str, code_digest: str) -> None: ...

    def activate(self, code_key: str, generation_id: str) -> bool: ...

    def invalidate(self, code_key: str, generation_id: str) -> None: ...

    def active_generation(self, code_key: str) -> str | None: ...

    def verify_and_consume(
        self,
        code_key: str,
        generation_id: str,
        code_digest: str,
    ) -> bool: ...


class RedisLuaScript:
    def __init__(self, source: str) -> None:
        self.source = source
        self.sha: str | None = None

    def execute(self, client, keys: list[str], args: list[object]):
        try:
            if self.sha is None:
                self.sha = client.script_load(self.source)
            try:
                return client.evalsha(self.sha, len(keys), *keys, *args)
            except NoScriptError:
                self.sha = client.script_load(self.source)
                return client.evalsha(self.sha, len(keys), *keys, *args)
        except RedisError as exc:
            raise SmsServiceUnavailable from exc


class RedisSmsVerificationStore:
    reserve_script = RedisLuaScript(RESERVE_SCRIPT)
    activate_script = RedisLuaScript(ACTIVATE_SCRIPT)
    invalidate_script = RedisLuaScript(INVALIDATE_SCRIPT)
    verify_script = RedisLuaScript(VERIFY_SCRIPT)

    def __init__(self, client=None) -> None:
        try:
            self.client = client or get_redis_connection("default")
        except Exception as exc:
            raise SmsServiceUnavailable from exc

    def reserve(self, keys: SmsRedisKeys, generation_id: str, code_digest: str) -> None:
        result = self.reserve_script.execute(
            self.client,
            [
                keys.code,
                keys.cooldown,
                keys.phone_limit,
                keys.ip_limit,
                keys.combination_limit,
            ],
            [
                generation_id,
                code_digest,
                settings.SMS_CODE_TTL_SECONDS,
                settings.SMS_RESEND_COOLDOWN_SECONDS,
                settings.SMS_LIMIT_PHONE_COUNT,
                settings.SMS_LIMIT_PHONE_WINDOW_SECONDS,
                settings.SMS_LIMIT_IP_COUNT,
                settings.SMS_LIMIT_IP_WINDOW_SECONDS,
                settings.SMS_LIMIT_COMBINATION_COUNT,
                settings.SMS_LIMIT_COMBINATION_WINDOW_SECONDS,
            ],
        )
        if _decode(result) == "rate_limited":
            raise SmsRateLimited

    def activate(self, code_key: str, generation_id: str) -> bool:
        result = self.activate_script.execute(
            self.client,
            [code_key],
            [generation_id],
        )
        return _decode(result) == "activated"

    def invalidate(self, code_key: str, generation_id: str) -> None:
        self.invalidate_script.execute(
            self.client,
            [code_key],
            [generation_id],
        )

    def active_generation(self, code_key: str) -> str | None:
        try:
            values = self.client.hmget(code_key, "generation_id", "state")
        except RedisError as exc:
            raise SmsServiceUnavailable from exc
        generation_id, state = (_decode(value) for value in values)
        if not generation_id or state != "active":
            return None
        return generation_id

    def verify_and_consume(
        self,
        code_key: str,
        generation_id: str,
        code_digest: str,
    ) -> bool:
        result = self.verify_script.execute(
            self.client,
            [code_key],
            [generation_id, code_digest, settings.SMS_MAX_ATTEMPTS],
        )
        return _decode(result) == "consumed"


def _decode(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value or "")


def sms_redis_keys(
    phone_fingerprint: str,
    ip_fingerprint: str,
    combination_fingerprint: str,
    purpose: SmsPurpose,
) -> SmsRedisKeys:
    prefix = "auth:sms:v1"
    return SmsRedisKeys(
        code=f"{prefix}:code:{phone_fingerprint}:{purpose.value}",
        cooldown=f"{prefix}:cooldown:{phone_fingerprint}",
        phone_limit=f"{prefix}:limit:phone:{phone_fingerprint}",
        ip_limit=f"{prefix}:limit:ip:{ip_fingerprint}",
        combination_limit=f"{prefix}:limit:combination:{combination_fingerprint}",
    )
