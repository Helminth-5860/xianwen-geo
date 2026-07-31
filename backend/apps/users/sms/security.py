import ipaddress
from hashlib import sha256
from hmac import new as hmac_new

from django.conf import settings

from .purposes import SmsPurpose

DERIVATION_CONTEXT = b"xianwen:sms-verification:v1:"


def _master_key() -> bytes:
    return settings.SMS_VERIFICATION_HMAC_KEY.encode("utf-8")


def derive_subkey(label: str) -> bytes:
    return hmac_new(_master_key(), DERIVATION_CONTEXT + label.encode("ascii"), sha256).digest()


def _fingerprint(label: str, value: str) -> str:
    return hmac_new(derive_subkey(label), value.encode("utf-8"), sha256).hexdigest()


def phone_fingerprint(normalized_phone: str) -> str:
    return _fingerprint("phone-fingerprint", normalized_phone)


def ip_fingerprint(ip_address: str) -> str:
    return _fingerprint("ip-fingerprint", ip_address)


def combination_fingerprint(normalized_phone: str, ip_address: str) -> str:
    return _fingerprint("phone-ip-fingerprint", f"{normalized_phone}\0{ip_address}")


def verification_code_digest(
    normalized_phone: str,
    purpose: SmsPurpose,
    generation_id: str,
    code: str,
) -> str:
    message = f"{normalized_phone}\0{purpose.value}\0{generation_id}\0{code}"
    return _fingerprint("verification-code-digest", message)


def _valid_ip(value: str) -> str | None:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def _trusted_proxy(remote_address: str) -> bool:
    try:
        remote_ip = ipaddress.ip_address(remote_address)
    except ValueError:
        return False
    return any(remote_ip in network for network in settings.TRUSTED_PROXY_NETWORKS)


def client_ip_address(request) -> str:
    remote_address = _valid_ip(request.META.get("REMOTE_ADDR", "")) or "0.0.0.0"
    trusted_hops = settings.TRUSTED_PROXY_HOPS
    if trusted_hops <= 0 or not _trusted_proxy(remote_address):
        return remote_address

    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    forwarded_parts = [part.strip() for part in forwarded.split(",") if part.strip()]
    chain = [_valid_ip(part) for part in forwarded_parts]
    if len(chain) < trusted_hops or any(candidate is None for candidate in chain):
        return remote_address
    return str(chain[-trusted_hops])
