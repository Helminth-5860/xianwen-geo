import re

import pytest

from apps.users.sms.exceptions import SmsServiceUnavailable
from apps.users.sms.providers import MockSmsProvider, UnavailableSmsProvider
from apps.users.sms.service import send_verification_code
from tests.sms_fakes import MemorySmsStore


def test_mock_provider_receives_random_six_digit_codes_only_in_process():
    provider = MockSmsProvider()

    for index in range(12):
        send_verification_code(
            f"13800138{index:03d}",
            "register",
            "192.0.2.1",
            provider=provider,
            store=MemorySmsStore(),
        )

    codes = [message.code for message in provider.outbox]
    assert all(re.fullmatch(r"\d{6}", code) for code in codes)
    assert len(set(codes)) > 1
    assert "123456" not in codes


def test_locally_unavailable_provider_does_not_consume_redis_limits():
    store = MemorySmsStore()

    with pytest.raises(SmsServiceUnavailable):
        send_verification_code(
            "13800138000",
            "login",
            "192.0.2.1",
            provider=UnavailableSmsProvider(),
            store=store,
        )

    assert store.reserve_calls == 0
