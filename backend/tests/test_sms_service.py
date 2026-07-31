from concurrent.futures import ThreadPoolExecutor

import pytest

from apps.users.sms.exceptions import SmsServiceUnavailable
from apps.users.sms.providers import MockSmsProvider, UnavailableSmsProvider
from apps.users.sms.purposes import SmsPurpose
from apps.users.sms.security import verification_code_digest
from apps.users.sms.service import send_verification_code, verify_and_consume
from apps.users.sms.store import SmsRedisKeys
from tests.sms_fakes import MemorySmsStore


class FailingProvider(MockSmsProvider):
    def send_verification_code(self, **kwargs) -> None:
        raise TimeoutError("provider details must stay internal")


def send_with_code(monkeypatch, store, provider, code, purpose="register"):
    monkeypatch.setattr(
        "apps.users.sms.service.generate_verification_code",
        lambda: code,
    )
    return send_verification_code(
        "13800138000",
        purpose,
        "192.0.2.1",
        provider=provider,
        store=store,
    )


def test_success_consumes_once_and_replay_fails(monkeypatch):
    store = MemorySmsStore()
    provider = MockSmsProvider()
    send_with_code(monkeypatch, store, provider, "483920")

    assert verify_and_consume("13800138000", "register", "483920", store=store)
    assert not verify_and_consume("13800138000", "register", "483920", store=store)


def test_resend_replaces_old_code_for_same_phone_and_purpose(monkeypatch):
    store = MemorySmsStore()
    provider = MockSmsProvider()
    send_with_code(monkeypatch, store, provider, "111928")
    send_with_code(monkeypatch, store, provider, "725304")

    assert not verify_and_consume("13800138000", "register", "111928", store=store)
    assert verify_and_consume("13800138000", "register", "725304", store=store)


def test_purposes_are_isolated(monkeypatch):
    store = MemorySmsStore()
    provider = MockSmsProvider()
    send_with_code(monkeypatch, store, provider, "312984", "register")
    send_with_code(monkeypatch, store, provider, "840192", "login")

    assert verify_and_consume("13800138000", "register", "312984", store=store)
    assert verify_and_consume("13800138000", "login", "840192", store=store)


def test_fifth_wrong_attempt_invalidates_code(monkeypatch):
    store = MemorySmsStore()
    send_with_code(monkeypatch, store, MockSmsProvider(), "983127")

    for _ in range(5):
        assert not verify_and_consume("13800138000", "register", "000000", store=store)
    assert not verify_and_consume("13800138000", "register", "983127", store=store)


def test_concurrent_correct_verification_has_one_winner(monkeypatch):
    store = MemorySmsStore()
    send_with_code(monkeypatch, store, MockSmsProvider(), "675492")

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(
            executor.map(
                lambda _: verify_and_consume(
                    "13800138000",
                    "register",
                    "675492",
                    store=store,
                ),
                range(16),
            )
        )

    assert results.count(True) == 1


def test_provider_attempt_failure_never_activates_code(monkeypatch):
    store = MemorySmsStore()

    with pytest.raises(SmsServiceUnavailable) as error:
        send_with_code(monkeypatch, store, FailingProvider(), "832905")

    assert str(error.value) == ""
    assert not verify_and_consume("13800138000", "register", "832905", store=store)
    assert store.reserve_calls == 1


def test_old_provider_result_cannot_activate_new_generation():
    store = MemorySmsStore()
    keys = SmsRedisKeys("code", "cooldown", "phone", "ip", "combination")
    first_digest = verification_code_digest(
        "+8613800138000", SmsPurpose.REGISTER, "old-generation", "123987"
    )
    second_digest = verification_code_digest(
        "+8613800138000", SmsPurpose.REGISTER, "new-generation", "729301"
    )
    store.reserve(keys, "old-generation", first_digest)
    store.reserve(keys, "new-generation", second_digest)

    assert not store.activate(keys.code, "old-generation")
    assert store.activate(keys.code, "new-generation")


def test_suppressed_delivery_uses_limits_without_provider_or_challenge(monkeypatch):
    store = MemorySmsStore()
    provider = MockSmsProvider()
    send_with_code(monkeypatch, store, provider, "438921", "login")
    assert provider.outbox

    send_verification_code(
        "13800138000",
        "login",
        "192.0.2.1",
        provider=provider,
        store=store,
        suppress_delivery=True,
    )

    assert len(provider.outbox) == 1
    assert not verify_and_consume("13800138000", "login", "438921", store=store)
    assert store.reserve_calls == 2


def test_suppressed_delivery_still_fails_when_provider_is_unavailable():
    store = MemorySmsStore()

    with pytest.raises(SmsServiceUnavailable):
        send_verification_code(
            "13800138000",
            "password_reset",
            "192.0.2.1",
            provider=UnavailableSmsProvider(),
            store=store,
            suppress_delivery=True,
        )

    assert store.reserve_calls == 0
