from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

from .phone_numbers import hmac_fingerprint, phone_fingerprint


class LoginRateLimitUnavailable(Exception):
    pass


@dataclass(frozen=True)
class LoginRateLimitKeys:
    combination: str
    phone: str
    ip: str


def login_rate_limit_keys(normalized_phone: str, ip_address: str) -> LoginRateLimitKeys:
    phone_hash = phone_fingerprint(normalized_phone)
    ip_hash = hmac_fingerprint("ip", ip_address)
    combination_hash = hmac_fingerprint("phone_ip", f"{normalized_phone}|{ip_address}")
    return LoginRateLimitKeys(
        combination=combination_hash,
        phone=phone_hash,
        ip=ip_hash,
    )


class LoginRateLimiter:
    def __init__(self, namespace: str = "password-login"):
        self.namespace = namespace
        self.window_seconds = settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS
        self.lock_seconds = settings.LOGIN_RATE_LIMIT_LOCK_SECONDS
        self.thresholds = {
            "combination": settings.LOGIN_RATE_LIMIT_COMBINATION_FAILURES,
            "phone": settings.LOGIN_RATE_LIMIT_PHONE_FAILURES,
            "ip": settings.LOGIN_RATE_LIMIT_IP_FAILURES,
        }

    def _cache_key(self, scope: str, fingerprint: str, suffix: str) -> str:
        return f"auth:{self.namespace}:{scope}:{fingerprint}:{suffix}"

    def ensure_allowed(self, keys: LoginRateLimitKeys) -> None:
        try:
            if any(
                cache.get(self._cache_key(scope, fingerprint, "lock"))
                for scope, fingerprint in vars(keys).items()
            ):
                raise PermissionError
        except PermissionError:
            raise
        except Exception as exc:
            raise LoginRateLimitUnavailable from exc

    def register_failure(self, keys: LoginRateLimitKeys) -> bool:
        limited = False
        try:
            for scope, fingerprint in vars(keys).items():
                counter_key = self._cache_key(scope, fingerprint, "failures")
                if cache.add(counter_key, 1, timeout=self.window_seconds):
                    count = 1
                else:
                    count = cache.incr(counter_key)
                if count >= self.thresholds[scope]:
                    cache.set(
                        self._cache_key(scope, fingerprint, "lock"),
                        1,
                        timeout=self.lock_seconds,
                    )
                    limited = True
        except Exception as exc:
            raise LoginRateLimitUnavailable from exc
        return limited

    def clear_successful_combination(self, keys: LoginRateLimitKeys) -> None:
        try:
            cache.delete_many(
                [
                    self._cache_key("combination", keys.combination, "failures"),
                    self._cache_key("combination", keys.combination, "lock"),
                ]
            )
        except Exception as exc:
            raise LoginRateLimitUnavailable from exc
