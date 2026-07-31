from ipaddress import ip_network

from django.test import RequestFactory

from apps.users.sms.purposes import SmsPurpose
from apps.users.sms.security import (
    client_ip_address,
    combination_fingerprint,
    derive_subkey,
    ip_fingerprint,
    phone_fingerprint,
    verification_code_digest,
)


def test_hmac_subkeys_are_isolated_and_fingerprints_hide_inputs(settings):
    settings.SMS_VERIFICATION_HMAC_KEY = "isolated-test-master-key"
    labels = (
        "phone-fingerprint",
        "ip-fingerprint",
        "phone-ip-fingerprint",
        "verification-code-digest",
    )

    assert len({derive_subkey(label) for label in labels}) == len(labels)
    phone = "+8613800138000"
    ip = "192.0.2.8"
    values = (
        phone_fingerprint(phone),
        ip_fingerprint(ip),
        combination_fingerprint(phone, ip),
    )
    for value in values:
        assert len(value) == 64
        assert phone not in value
        assert ip not in value


def test_same_code_has_different_digest_across_purpose_and_generation(settings):
    settings.SMS_VERIFICATION_HMAC_KEY = "digest-domain-separation-key"
    phone = "+8613800138000"
    code = "392817"

    digests = {
        verification_code_digest(phone, SmsPurpose.REGISTER, "generation-a", code),
        verification_code_digest(phone, SmsPurpose.LOGIN, "generation-a", code),
        verification_code_digest(phone, SmsPurpose.REGISTER, "generation-b", code),
    }

    assert len(digests) == 3


def test_untrusted_forwarded_for_is_ignored(settings):
    settings.TRUSTED_PROXY_HOPS = 1
    settings.TRUSTED_PROXY_NETWORKS = (ip_network("10.0.0.0/8"),)
    request = RequestFactory().post(
        "/api/v1/auth/sms/send",
        REMOTE_ADDR="192.0.2.10",
        HTTP_X_FORWARDED_FOR="203.0.113.99",
    )

    assert client_ip_address(request) == "192.0.2.10"


def test_trusted_proxy_uses_configured_hop_from_right(settings):
    settings.TRUSTED_PROXY_HOPS = 1
    settings.TRUSTED_PROXY_NETWORKS = (ip_network("10.0.0.0/8"),)
    request = RequestFactory().post(
        "/api/v1/auth/sms/send",
        REMOTE_ADDR="10.0.0.8",
        HTTP_X_FORWARDED_FOR="198.51.100.1, 203.0.113.7",
    )

    assert client_ip_address(request) == "203.0.113.7"
