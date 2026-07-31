from hashlib import sha1

from redis.exceptions import NoScriptError

from apps.users.sms.store import RedisLuaScript


class NoScriptOnceClient:
    def __init__(self) -> None:
        self.loads = 0
        self.calls = 0

    def script_load(self, source):
        self.loads += 1
        return sha1(source.encode(), usedforsecurity=False).hexdigest()

    def evalsha(self, sha, key_count, *values):
        self.calls += 1
        if self.calls == 1:
            raise NoScriptError
        return b"recovered"


def test_evalsha_recovers_after_noscript():
    client = NoScriptOnceClient()
    script = RedisLuaScript("return 'recovered'")

    result = script.execute(client, ["key"], ["arg"])

    assert result == b"recovered"
    assert client.loads == 2
    assert client.calls == 2
