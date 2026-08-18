from dataclasses import dataclass
from functools import lru_cache
from threading import Lock
from typing import Protocol

from django.conf import settings

from .exceptions import SmsServiceUnavailable
from .purposes import SmsPurpose


class SmsProvider(Protocol):
    @property
    def locally_available(self) -> bool: ...

    def send_verification_code(
        self,
        *,
        phone: str,
        purpose: SmsPurpose,
        code: str,
        expires_in: int,
    ) -> None: ...


@dataclass(frozen=True, repr=False)
class MockSmsMessage:
    phone: str
    purpose: SmsPurpose
    code: str
    expires_in: int


class MockSmsProvider:
    def __init__(self) -> None:
        self._outbox: list[MockSmsMessage] = []
        self._lock = Lock()

    @property
    def locally_available(self) -> bool:
        return True

    @property
    def outbox(self) -> tuple[MockSmsMessage, ...]:
        with self._lock:
            return tuple(self._outbox)

    def send_verification_code(
        self,
        *,
        phone: str,
        purpose: SmsPurpose,
        code: str,
        expires_in: int,
    ) -> None:
        with self._lock:
            self._outbox.append(
                MockSmsMessage(
                    phone=phone,
                    purpose=purpose,
                    code=code,
                    expires_in=expires_in,
                )
            )


class UnavailableSmsProvider:
    @property
    def locally_available(self) -> bool:
        return False

    def send_verification_code(
        self,
        *,
        phone: str,
        purpose: SmsPurpose,
        code: str,
        expires_in: int,
    ) -> None:
        raise SmsServiceUnavailable


@lru_cache(maxsize=4)
def _provider_for_name(provider_name: str) -> SmsProvider:
    if provider_name == "mock":
        return MockSmsProvider()
    if provider_name == "tencent":
        from .tencent import TencentSmsProvider

        return TencentSmsProvider.from_settings()
    return UnavailableSmsProvider()


def get_sms_provider() -> SmsProvider:
    return _provider_for_name(settings.SMS_PROVIDER)
