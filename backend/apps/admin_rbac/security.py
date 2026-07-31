import ipaddress
import json
import secrets
import time
from dataclasses import dataclass
from hashlib import sha256
from hmac import new as hmac_new
from typing import Any

from django.conf import settings
from django.contrib.auth import login, logout
from django.db import transaction
from django.db.models import F
from django_redis import get_redis_connection  # type: ignore[import-untyped]
from redis.exceptions import NoScriptError, RedisError

from apps.core.request_ids import validate_request_id
from apps.users.authentication import SESSION_VERSION_KEY
from apps.users.models import User
from apps.users.services import client_ip_address
from apps.users.sms.exceptions import SmsRateLimited, SmsServiceUnavailable
from apps.users.sms.providers import SmsProvider, get_sms_provider
from apps.users.sms.purposes import SmsPurpose
from apps.users.sms.security import derive_subkey
from apps.users.sms.service import generate_verification_code

from .models import (
    AdminProfile,
    AdminRole,
    AdminSecurityEvent,
    IpAllowlistStatus,
    SuperuserSecurityPolicy,
)

ADMIN_AUTHENTICATED_KEY = "_xianwen_admin_authenticated"
ADMIN_AUTH_TIME_KEY = "_xianwen_admin_auth_time"
ADMIN_PROFILE_ID_KEY = "_xianwen_admin_profile_id"
ADMIN_PROFILE_VERSION_KEY = "_xianwen_admin_profile_version"
ADMIN_ROLE_ID_KEY = "_xianwen_admin_role_id"
ADMIN_ROLE_VERSION_KEY = "_xianwen_admin_role_version"
ADMIN_ROLE_SECURITY_VERSION_KEY = "_xianwen_admin_role_security_version"
ADMIN_POLICY_VERSION_KEY = "_xianwen_admin_policy_version"
ADMIN_AUTH_FACTORS_KEY = "_xianwen_admin_auth_factors"
ADMIN_IP_FINGERPRINT_KEY = "_xianwen_admin_ip_fingerprint"


class AdminSecurityUnavailable(Exception):
    pass


class AdminChallengeInvalid(Exception):
    pass


class AdminChallengeExpired(Exception):
    pass


class AdminChallengeReplayed(Exception):
    pass


class AdminIpNotAllowed(Exception):
    pass


class SecurityPolicyVersionConflict(Exception):
    pass


class AdminReauthFailed(Exception):
    pass


class AdminReauthRateLimited(Exception):
    pass


class LockoutConfirmationRequired(Exception):
    pass


@dataclass(frozen=True)
class AdminSecuritySnapshot:
    user: User
    profile: AdminProfile
    role: AdminRole | None
    policy: SuperuserSecurityPolicy | None
    require_sms_2fa: bool
    ip_fingerprint: str
    user_agent_digest: str


def _hmac(label: str, value: str) -> str:
    return hmac_new(derive_subkey(f"admin-{label}"), value.encode("utf-8"), sha256).hexdigest()


def admin_ip_fingerprint(ip_address: str) -> str:
    return _hmac("ip-fingerprint", ip_address)


def admin_user_agent_digest(user_agent: str) -> str:
    return _hmac("user-agent-digest", user_agent[:512])


def admin_identity(user: User) -> bool:
    return bool(
        user.is_superuser or user.is_staff or AdminProfile.objects.filter(user_id=user.pk).exists()
    )


def normalize_network(value: str) -> tuple[str, int]:
    if not isinstance(value, str) or not value or any(ord(char) < 32 for char in value):
        raise ValueError("IP/CIDR 格式不正确。")
    if any(marker in value for marker in ("*", "?", "[", "]", "(", ")", "\\")):
        raise ValueError("IP/CIDR 格式不正确。")
    try:
        network = ipaddress.ip_network(value.strip(), strict=False)
    except ValueError as exc:
        raise ValueError("IP/CIDR 格式不正确。") from exc
    return str(network), network.version


def _ip_allowed(ip_address: str, *, enabled: bool, entries) -> bool:
    if not enabled:
        return True
    try:
        candidate = ipaddress.ip_address(ip_address)
        networks = [ipaddress.ip_network(item.network_cidr) for item in entries]
    except (ValueError, TypeError) as exc:
        raise AdminSecurityUnavailable from exc
    return bool(networks) and any(candidate in network for network in networks)


def security_snapshot(user: User, request) -> AdminSecuritySnapshot:
    try:
        profile = AdminProfile.objects.select_related("role").get(user=user)
    except AdminProfile.DoesNotExist as exc:
        raise AdminChallengeInvalid from exc
    if (
        not user.is_active
        or user.account_status not in User.ACTIVE_ACCOUNT_STATUSES
        or profile.admin_status != AdminProfile.Status.ACTIVE
    ):
        raise AdminChallengeInvalid
    ip_address = client_ip_address(request)
    user_agent = (request.META.get("HTTP_USER_AGENT", "") or "")[:512]
    policy = None
    entries: Any
    if user.is_superuser:
        if not user.is_staff or profile.role_id is not None:
            raise AdminChallengeInvalid
        policy, _ = SuperuserSecurityPolicy.objects.get_or_create(user=user)
        entries = policy.ip_allowlist_entries.filter(status=IpAllowlistStatus.ACTIVE)
        enabled = policy.ip_allowlist_enabled
        require_sms_2fa = True
    else:
        role = profile.role
        if not user.is_staff or role is None or role.status != AdminRole.Status.ACTIVE:
            raise AdminChallengeInvalid
        entries = role.ip_allowlist_entries.filter(status=IpAllowlistStatus.ACTIVE)
        enabled = role.ip_allowlist_enabled
        require_sms_2fa = role.require_sms_2fa
    try:
        allowed = _ip_allowed(ip_address, enabled=enabled, entries=list(entries))
    except Exception as exc:
        if isinstance(exc, AdminSecurityUnavailable):
            raise
        raise AdminSecurityUnavailable from exc
    if not allowed:
        raise AdminIpNotAllowed
    return AdminSecuritySnapshot(
        user=user,
        profile=profile,
        role=profile.role,
        policy=policy,
        require_sms_2fa=require_sms_2fa,
        ip_fingerprint=admin_ip_fingerprint(ip_address),
        user_agent_digest=admin_user_agent_digest(user_agent),
    )


def record_security_event(
    *,
    request,
    event_type: str,
    subject: User | None = None,
    actor: User | None = None,
    snapshot: AdminSecuritySnapshot | None = None,
    failure_reason: str = "",
) -> AdminSecurityEvent:
    request_id = validate_request_id(getattr(request, "request_id", ""))
    if request_id is None:
        raise ValueError("安全事件必须包含规范 request_id。")
    ip_fp = admin_ip_fingerprint(client_ip_address(request))
    ua_digest = admin_user_agent_digest((request.META.get("HTTP_USER_AGENT", "") or "")[:512])
    return AdminSecurityEvent.objects.create(
        actor=actor,
        subject=subject,
        event_type=event_type,
        request_id=request_id,
        ip_fingerprint=ip_fp,
        user_agent_digest=ua_digest,
        admin_profile_version=snapshot.profile.version if snapshot else None,
        role_version=snapshot.role.version if snapshot and snapshot.role else None,
        role_security_version=(
            snapshot.role.security_version if snapshot and snapshot.role else None
        ),
        policy_version=(snapshot.policy.security_version if snapshot and snapshot.policy else None),
        stable_failure_reason=failure_reason,
    )


def start_admin_session(request, snapshot: AdminSecuritySnapshot, factors: str) -> None:
    login(request, snapshot.user, backend="django.contrib.auth.backends.ModelBackend")
    request.session[SESSION_VERSION_KEY] = snapshot.user.session_version
    request.session[ADMIN_AUTHENTICATED_KEY] = True
    request.session[ADMIN_AUTH_TIME_KEY] = int(time.time())
    request.session[ADMIN_PROFILE_ID_KEY] = str(snapshot.profile.pk)
    request.session[ADMIN_PROFILE_VERSION_KEY] = snapshot.profile.version
    request.session[ADMIN_ROLE_ID_KEY] = str(snapshot.role.pk) if snapshot.role else None
    request.session[ADMIN_ROLE_VERSION_KEY] = snapshot.role.version if snapshot.role else None
    request.session[ADMIN_ROLE_SECURITY_VERSION_KEY] = (
        snapshot.role.security_version if snapshot.role else None
    )
    request.session[ADMIN_POLICY_VERSION_KEY] = (
        snapshot.policy.security_version if snapshot.policy else None
    )
    request.session[ADMIN_AUTH_FACTORS_KEY] = factors
    request.session[ADMIN_IP_FINGERPRINT_KEY] = snapshot.ip_fingerprint
    request.session.set_expiry(0)


def clear_admin_session(request) -> None:
    logout(request)


def validate_admin_session(request) -> AdminSecuritySnapshot | None:
    user = request.user
    if not user.is_authenticated or request.session.get(ADMIN_AUTHENTICATED_KEY) is not True:
        return None
    try:
        snapshot = security_snapshot(user, request)
    except (AdminChallengeInvalid, AdminIpNotAllowed, AdminSecurityUnavailable):
        clear_admin_session(request)
        return None
    expected = {
        ADMIN_PROFILE_ID_KEY: str(snapshot.profile.pk),
        ADMIN_PROFILE_VERSION_KEY: snapshot.profile.version,
        ADMIN_ROLE_ID_KEY: str(snapshot.role.pk) if snapshot.role else None,
        ADMIN_ROLE_VERSION_KEY: snapshot.role.version if snapshot.role else None,
        ADMIN_ROLE_SECURITY_VERSION_KEY: snapshot.role.security_version if snapshot.role else None,
        ADMIN_POLICY_VERSION_KEY: snapshot.policy.security_version if snapshot.policy else None,
        ADMIN_IP_FINGERPRINT_KEY: snapshot.ip_fingerprint,
    }
    factors = request.session.get(ADMIN_AUTH_FACTORS_KEY)
    required_factors = "password+sms" if snapshot.require_sms_2fa else "password"
    if (
        any(request.session.get(key) != value for key, value in expected.items())
        or factors != required_factors
    ):
        clear_admin_session(request)
        return None
    return snapshot


CREATE_CHALLENGE_SCRIPT = """
redis.call('HSET', KEYS[1],
  'payload', ARGV[1], 'state', 'password_verified',
  'generation_id', '', 'code_digest', '', 'attempts', '0')
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
return 'created'
"""

RESERVE_CODE_SCRIPT = """
if redis.call('HGET', KEYS[1], 'state') == false then return 'missing' end
if redis.call('EXISTS', KEYS[2]) == 1 then return 'rate_limited' end
for index=3,5 do
  local current = tonumber(redis.call('GET', KEYS[index]) or '0')
  if current >= tonumber(ARGV[(index - 3) * 2 + 4]) then return 'rate_limited' end
end
for index=3,5 do
  local count = redis.call('INCR', KEYS[index])
  if count == 1 then redis.call('EXPIRE', KEYS[index], tonumber(ARGV[(index - 3) * 2 + 5])) end
end
redis.call('SET', KEYS[2], '1', 'EX', tonumber(ARGV[3]))
redis.call('HSET', KEYS[1],
  'generation_id', ARGV[1], 'code_digest', ARGV[2],
  'state', 'sms_pending', 'attempts', '0')
return 'reserved'
"""

ACTIVATE_CODE_SCRIPT = """
if redis.call('HGET', KEYS[1], 'generation_id') ~= ARGV[1] then return 'stale' end
if redis.call('HGET', KEYS[1], 'state') ~= 'sms_pending' then return 'stale' end
redis.call('HSET', KEYS[1], 'state', 'sms_active')
return 'activated'
"""

INVALIDATE_CODE_SCRIPT = """
if redis.call('HGET', KEYS[1], 'generation_id') == ARGV[1] then
  redis.call('HSET', KEYS[1], 'state', 'invalid')
  return 'invalidated'
end
return 'stale'
"""

VERIFY_CODE_SCRIPT = """
local state = redis.call('HGET', KEYS[1], 'state')
if state == false then return 'expired' end
if state == 'consumed' then return 'replayed' end
if state ~= 'sms_active' then return 'invalid' end
if redis.call('HGET', KEYS[1], 'code_digest') == ARGV[1] then
  redis.call('HSET', KEYS[1], 'state', 'consumed', 'code_digest', '')
  redis.call('EXPIRE', KEYS[1], 60)
  return 'consumed'
end
local attempts = redis.call('HINCRBY', KEYS[1], 'attempts', 1)
if attempts >= tonumber(ARGV[2]) then
  redis.call('HSET', KEYS[1], 'state', 'invalid', 'code_digest', '')
end
return 'invalid'
"""


class RedisScript:
    def __init__(self, source: str) -> None:
        self.source = source
        self.sha: str | None = None

    def run(self, client, keys: list[str], args: list[object]):
        try:
            if self.sha is None:
                self.sha = client.script_load(self.source)
            try:
                return client.evalsha(self.sha, len(keys), *keys, *args)
            except NoScriptError:
                self.sha = client.script_load(self.source)
                return client.evalsha(self.sha, len(keys), *keys, *args)
        except RedisError as exc:
            raise AdminSecurityUnavailable from exc


class AdminChallengeStore:
    create_script = RedisScript(CREATE_CHALLENGE_SCRIPT)
    reserve_script = RedisScript(RESERVE_CODE_SCRIPT)
    activate_script = RedisScript(ACTIVATE_CODE_SCRIPT)
    invalidate_script = RedisScript(INVALIDATE_CODE_SCRIPT)
    verify_script = RedisScript(VERIFY_CODE_SCRIPT)

    def __init__(self, client=None) -> None:
        try:
            self.client = client or get_redis_connection("default")
        except Exception as exc:
            raise AdminSecurityUnavailable from exc

    @staticmethod
    def key(challenge_id: str) -> str:
        return f"auth:admin-login:v1:challenge:{_hmac('challenge-id', challenge_id)}"

    def create(self, challenge_id: str, payload: dict[str, object]) -> None:
        self.create_script.run(
            self.client,
            [self.key(challenge_id)],
            [json.dumps(payload, separators=(",", ":")), settings.ADMIN_CHALLENGE_TTL_SECONDS],
        )

    def payload(self, challenge_id: str) -> tuple[dict[str, object], str]:
        try:
            values = self.client.hmget(self.key(challenge_id), "payload", "state")
        except RedisError as exc:
            raise AdminSecurityUnavailable from exc
        if not values[0]:
            raise AdminChallengeExpired
        try:
            payload = json.loads(values[0].decode() if isinstance(values[0], bytes) else values[0])
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AdminChallengeInvalid from exc
        state = values[1].decode() if isinstance(values[1], bytes) else str(values[1])
        return payload, state

    def reserve_code(
        self,
        challenge_id: str,
        generation_id: str,
        digest: str,
        phone_fp: str,
        ip_fp: str,
        combination_fp: str,
    ) -> None:
        prefix = "auth:admin-login:v1"
        result = self.reserve_script.run(
            self.client,
            [
                self.key(challenge_id),
                f"{prefix}:cooldown:{phone_fp}",
                f"{prefix}:limit:account:{phone_fp}",
                f"{prefix}:limit:ip:{ip_fp}",
                f"{prefix}:limit:combination:{combination_fp}",
            ],
            [
                generation_id,
                digest,
                settings.SMS_RESEND_COOLDOWN_SECONDS,
                settings.SMS_LIMIT_PHONE_COUNT,
                settings.SMS_LIMIT_PHONE_WINDOW_SECONDS,
                settings.SMS_LIMIT_IP_COUNT,
                settings.SMS_LIMIT_IP_WINDOW_SECONDS,
                settings.SMS_LIMIT_COMBINATION_COUNT,
                settings.SMS_LIMIT_COMBINATION_WINDOW_SECONDS,
            ],
        )
        decoded = result.decode() if isinstance(result, bytes) else str(result)
        if decoded == "rate_limited":
            raise SmsRateLimited
        if decoded != "reserved":
            raise AdminChallengeInvalid

    def activate(self, challenge_id: str, generation_id: str) -> bool:
        result = self.activate_script.run(self.client, [self.key(challenge_id)], [generation_id])
        return (result.decode() if isinstance(result, bytes) else str(result)) == "activated"

    def invalidate(self, challenge_id: str, generation_id: str) -> None:
        self.invalidate_script.run(self.client, [self.key(challenge_id)], [generation_id])

    def verify(self, challenge_id: str, digest: str) -> str:
        result = self.verify_script.run(
            self.client,
            [self.key(challenge_id)],
            [digest, settings.SMS_MAX_ATTEMPTS],
        )
        return result.decode() if isinstance(result, bytes) else str(result)


def _challenge_payload(snapshot: AdminSecuritySnapshot) -> dict[str, object]:
    return {
        "user_id": str(snapshot.user.pk),
        "session_version": snapshot.user.session_version,
        "profile_id": str(snapshot.profile.pk),
        "profile_version": snapshot.profile.version,
        "role_id": str(snapshot.role.pk) if snapshot.role else None,
        "role_version": snapshot.role.version if snapshot.role else None,
        "role_security_version": snapshot.role.security_version if snapshot.role else None,
        "policy_id": str(snapshot.policy.pk) if snapshot.policy else None,
        "policy_version": snapshot.policy.security_version if snapshot.policy else None,
        "require_sms_2fa": snapshot.require_sms_2fa,
        "ip_fingerprint": snapshot.ip_fingerprint,
        "user_agent_digest": snapshot.user_agent_digest,
        "security_context_version": 1,
        "created_at": int(time.time()),
        "expires_at": int(time.time()) + settings.ADMIN_CHALLENGE_TTL_SECONDS,
    }


def create_admin_challenge(snapshot: AdminSecuritySnapshot, *, store=None) -> str:
    challenge_id = secrets.token_urlsafe(32)
    (store or AdminChallengeStore()).create(challenge_id, _challenge_payload(snapshot))
    return challenge_id


def _snapshot_matches_payload(snapshot: AdminSecuritySnapshot, payload: dict[str, object]) -> bool:
    expected = _challenge_payload(snapshot)
    for key in (
        "user_id",
        "session_version",
        "profile_id",
        "profile_version",
        "role_id",
        "role_version",
        "role_security_version",
        "policy_id",
        "policy_version",
        "require_sms_2fa",
        "ip_fingerprint",
        "user_agent_digest",
        "security_context_version",
    ):
        if payload.get(key) != expected.get(key):
            return False
    return True


def snapshot_for_challenge(challenge_id: str, request, *, store=None):
    resolved_store = store or AdminChallengeStore()
    payload, state = resolved_store.payload(challenge_id)
    if state == "consumed":
        raise AdminChallengeReplayed
    user_id = payload.get("user_id")
    if not isinstance(user_id, str):
        raise AdminChallengeInvalid
    try:
        user = User.objects.get(pk=user_id)
        snapshot = security_snapshot(user, request)
    except (User.DoesNotExist, ValueError) as exc:
        raise AdminChallengeInvalid from exc
    if not _snapshot_matches_payload(snapshot, payload):
        raise AdminChallengeInvalid
    return snapshot, payload, resolved_store


def _admin_code_digest(challenge_id: str, user_id: str, generation_id: str, code: str) -> str:
    return _hmac(
        "verification-code-digest",
        f"{challenge_id}\0{user_id}\0{SmsPurpose.ADMIN_LOGIN_2FA.value}\0{generation_id}\0{code}",
    )


def send_admin_second_factor(
    challenge_id: str,
    request,
    *,
    provider: SmsProvider | None = None,
    store=None,
) -> AdminSecuritySnapshot:
    snapshot, payload, resolved_store = snapshot_for_challenge(challenge_id, request, store=store)
    resolved_provider = provider or get_sms_provider()
    if not resolved_provider.locally_available:
        raise SmsServiceUnavailable
    generation_id = secrets.token_hex(16)
    code = generate_verification_code()
    digest = _admin_code_digest(challenge_id, str(snapshot.user.pk), generation_id, code)
    phone_fp = _hmac("phone-fingerprint", snapshot.user.phone)
    combination_fp = _hmac(
        "phone-ip-fingerprint", f"{snapshot.user.phone}\0{snapshot.ip_fingerprint}"
    )
    resolved_store.reserve_code(
        challenge_id,
        generation_id,
        digest,
        phone_fp,
        snapshot.ip_fingerprint,
        combination_fp,
    )
    try:
        resolved_provider.send_verification_code(
            phone=snapshot.user.phone,
            purpose=SmsPurpose.ADMIN_LOGIN_2FA,
            code=code,
            expires_in=settings.ADMIN_CHALLENGE_TTL_SECONDS,
        )
    except Exception as exc:
        resolved_store.invalidate(challenge_id, generation_id)
        raise SmsServiceUnavailable from exc
    if not resolved_store.activate(challenge_id, generation_id):
        raise SmsServiceUnavailable
    return snapshot


def verify_admin_second_factor(
    challenge_id: str, code: str, request, *, store=None
) -> AdminSecuritySnapshot:
    snapshot, payload, resolved_store = snapshot_for_challenge(challenge_id, request, store=store)
    if not isinstance(code, str) or len(code) != 6 or not code.isdigit():
        raise AdminChallengeInvalid
    try:
        values = resolved_store.client.hmget(resolved_store.key(challenge_id), "generation_id")
    except RedisError as exc:
        raise AdminSecurityUnavailable from exc
    generation = (
        values[0].decode() if values and isinstance(values[0], bytes) else str(values[0] or "")
    )
    if not generation:
        raise AdminChallengeInvalid
    digest = _admin_code_digest(challenge_id, str(snapshot.user.pk), generation, code)
    result = resolved_store.verify(challenge_id, digest)
    if result == "expired":
        raise AdminChallengeExpired
    if result == "replayed":
        raise AdminChallengeInvalid
    if result != "consumed":
        raise AdminChallengeInvalid
    return snapshot


def verify_current_password(user: User, password: str) -> None:
    if not isinstance(password, str) or not user.check_password(password):
        raise AdminReauthFailed


@transaction.atomic
def force_logout_admin(*, actor: User, profile_id, request) -> AdminProfile:
    if not actor.is_superuser:
        raise AdminReauthFailed
    profile = AdminProfile.objects.select_for_update().select_related("user").get(pk=profile_id)
    User.objects.filter(pk=profile.user_id).update(session_version=F("session_version") + 1)
    record_security_event(
        request=request,
        event_type="admin_forced_logout",
        actor=actor,
        subject=profile.user,
    )
    return profile
