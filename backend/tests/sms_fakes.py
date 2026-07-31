from hmac import compare_digest
from threading import Lock

from apps.users.sms.store import SmsRedisKeys


class MemorySmsStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self.challenges: dict[str, dict[str, object]] = {}
        self.reserve_calls = 0

    def reserve(self, keys: SmsRedisKeys, generation_id: str, code_digest: str) -> None:
        with self._lock:
            self.reserve_calls += 1
            self.challenges[keys.code] = {
                "generation_id": generation_id,
                "code_digest": code_digest,
                "state": "pending",
                "attempts": 0,
            }

    def activate(self, code_key: str, generation_id: str) -> bool:
        with self._lock:
            challenge = self.challenges.get(code_key)
            if challenge is None or challenge["generation_id"] != generation_id:
                return False
            if challenge["state"] != "pending":
                return False
            challenge["state"] = "active"
            return True

    def invalidate(self, code_key: str, generation_id: str) -> None:
        with self._lock:
            challenge = self.challenges.get(code_key)
            if challenge is not None and challenge["generation_id"] == generation_id:
                del self.challenges[code_key]

    def active_generation(self, code_key: str) -> str | None:
        with self._lock:
            challenge = self.challenges.get(code_key)
            if challenge is None or challenge["state"] != "active":
                return None
            return str(challenge["generation_id"])

    def verify_and_consume(
        self,
        code_key: str,
        generation_id: str,
        code_digest: str,
    ) -> bool:
        with self._lock:
            challenge = self.challenges.get(code_key)
            if (
                challenge is None
                or challenge["generation_id"] != generation_id
                or challenge["state"] != "active"
            ):
                return False
            if compare_digest(str(challenge["code_digest"]), code_digest):
                del self.challenges[code_key]
                return True
            challenge["attempts"] = int(challenge["attempts"]) + 1
            if int(challenge["attempts"]) >= 5:
                del self.challenges[code_key]
            return False
