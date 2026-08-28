from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from django.core.cache import cache
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from .models import PlatformAccount, PlatformAuthorizationSession
from .security import PublishingCredentialError, decrypt_secret, encrypt_secret
from .services import PublishingInputError, complete_authorization_session


class WechatComponentUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class WechatComponentConfig:
    app_id: str
    app_secret: str
    token: str
    encoding_aes_key: str
    redirect_url: str


def component_config() -> WechatComponentConfig | None:
    values = WechatComponentConfig(
        app_id=os.getenv("PUBLISHING_WECHAT_COMPONENT_APP_ID", "").strip(),
        app_secret=os.getenv("PUBLISHING_WECHAT_COMPONENT_APP_SECRET", "").strip(),
        token=os.getenv("PUBLISHING_WECHAT_COMPONENT_TOKEN", "").strip(),
        encoding_aes_key=os.getenv("PUBLISHING_WECHAT_COMPONENT_AES_KEY", "").strip(),
        redirect_url=os.getenv("PUBLISHING_WECHAT_COMPONENT_REDIRECT_URL", "").strip(),
    )
    if not all((values.app_id, values.app_secret, values.token, values.encoding_aes_key, values.redirect_url)):
        return None
    if len(values.encoding_aes_key) != 43:
        return None
    try:
        parsed = urlsplit(values.redirect_url)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if os.getenv("APP_ENV", "local").strip().lower() == "production" and parsed.scheme != "https":
        return None
    return values


def component_authorization_ready() -> bool:
    return component_config() is not None and bool(cache.get(_ticket_key(component_config().app_id)))


def _ticket_key(app_id: str) -> str:
    return f"publishing:wechat-component:{app_id}:verify-ticket"


def _token_key(app_id: str) -> str:
    return f"publishing:wechat-component:{app_id}:access-token"


def _signature(config: WechatComponentConfig, timestamp: str, nonce: str, encrypted: str) -> str:
    material = "".join(sorted((config.token, timestamp, nonce, encrypted)))
    return hashlib.sha1(material.encode("utf-8"), usedforsecurity=False).hexdigest()


def _verify_signature(config: WechatComponentConfig, supplied: str, timestamp: str, nonce: str, encrypted: str) -> bool:
    if not supplied or not timestamp or not nonce or not encrypted:
        return False
    return hmac.compare_digest(_signature(config, timestamp, nonce, encrypted), supplied)


def _aes_key(config: WechatComponentConfig) -> bytes:
    try:
        key = base64.b64decode(config.encoding_aes_key + "=")
    except Exception as exc:
        raise WechatComponentUnavailable("invalid_component_crypto") from exc
    if len(key) != 32:
        raise WechatComponentUnavailable("invalid_component_crypto")
    return key


def _unpad32(value: bytes) -> bytes:
    if not value:
        raise WechatComponentUnavailable("invalid_component_message")
    pad = value[-1]
    if pad < 1 or pad > 32 or value[-pad:] != bytes([pad]) * pad:
        raise WechatComponentUnavailable("invalid_component_message")
    return value[:-pad]


def decrypt_component_message(config: WechatComponentConfig, encrypted: str) -> str:
    try:
        ciphertext = base64.b64decode(encrypted)
        key = _aes_key(config)
        decryptor = Cipher(algorithms.AES(key), modes.CBC(key[:16])).decryptor()
        plaintext = _unpad32(decryptor.update(ciphertext) + decryptor.finalize())
        if len(plaintext) < 20:
            raise ValueError("short")
        message_length = struct.unpack("!I", plaintext[16:20])[0]
        message_end = 20 + message_length
        if message_length <= 0 or message_end > len(plaintext):
            raise ValueError("length")
        message = plaintext[20:message_end].decode("utf-8")
        app_id = plaintext[message_end:].decode("utf-8")
    except Exception as exc:
        raise WechatComponentUnavailable("invalid_component_message") from exc
    if app_id != config.app_id:
        raise WechatComponentUnavailable("component_app_mismatch")
    return message


def _xml_value(xml_text: str, name: str) -> str:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise WechatComponentUnavailable("invalid_component_message") from exc
    node = root.find(name)
    return (node.text or "").strip() if node is not None else ""


def _api_post(url: str, payload: dict, *, timeout: float = 15.0) -> dict:
    try:
        response = httpx.post(url, json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise WechatComponentUnavailable("wechat_component_unavailable") from exc
    if not isinstance(data, dict):
        raise WechatComponentUnavailable("wechat_component_invalid_response")
    errcode = data.get("errcode")
    if isinstance(errcode, int) and errcode != 0:
        raise WechatComponentUnavailable(f"wechat_component_error_{errcode}")
    return data


def component_access_token() -> str:
    config = component_config()
    if config is None:
        raise WechatComponentUnavailable("wechat_component_not_configured")
    cached = cache.get(_token_key(config.app_id))
    if isinstance(cached, str) and cached:
        return cached
    ticket = cache.get(_ticket_key(config.app_id))
    if not isinstance(ticket, str) or not ticket:
        raise WechatComponentUnavailable("wechat_component_ticket_missing")
    data = _api_post(
        "https://api.weixin.qq.com/cgi-bin/component/api_component_token",
        {
            "component_appid": config.app_id,
            "component_appsecret": config.app_secret,
            "component_verify_ticket": ticket,
        },
    )
    token = str(data.get("component_access_token") or "")
    expires_in = int(data.get("expires_in") or 7200)
    if not token:
        raise WechatComponentUnavailable("wechat_component_invalid_response")
    cache.set(_token_key(config.app_id), token, timeout=max(300, expires_in - 300))
    return token


def pre_auth_code() -> str:
    config = component_config()
    if config is None:
        raise WechatComponentUnavailable("wechat_component_not_configured")
    token = component_access_token()
    data = _api_post(
        f"https://api.weixin.qq.com/cgi-bin/component/api_create_preauthcode?component_access_token={quote(token)}",
        {"component_appid": config.app_id},
    )
    value = str(data.get("pre_auth_code") or "")
    if not value:
        raise WechatComponentUnavailable("wechat_component_invalid_response")
    return value


def _redirect_for_session(config: WechatComponentConfig, session_id) -> str:
    parsed = urlsplit(config.redirect_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["session_id"] = str(session_id)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def begin_wechat_component_authorization(session: PlatformAuthorizationSession) -> PlatformAuthorizationSession:
    config = component_config()
    if config is None:
        raise WechatComponentUnavailable("wechat_component_not_configured")
    code = pre_auth_code()
    redirect = _redirect_for_session(config, session.pk)
    action_url = (
        "https://mp.weixin.qq.com/cgi-bin/componentloginpage"
        f"?component_appid={quote(config.app_id)}"
        f"&pre_auth_code={quote(code)}"
        f"&redirect_uri={quote(redirect, safe='')}"
        "&auth_type=1"
    )
    session.status = PlatformAuthorizationSession.Status.WAITING_USER
    session.remote_session_ref = f"wechat-component:{session.pk}"
    session.action_url = action_url
    session.started_at = timezone.now()
    session.safe_error_code = ""
    session.save(
        update_fields=(
            "status",
            "remote_session_ref",
            "action_url",
            "started_at",
            "safe_error_code",
            "updated_at",
        )
    )
    return session


def _authorizer_info(authorizer_appid: str) -> dict:
    config = component_config()
    if config is None:
        return {}
    try:
        data = _api_post(
            f"https://api.weixin.qq.com/cgi-bin/component/api_get_authorizer_info?component_access_token={quote(component_access_token())}",
            {"component_appid": config.app_id, "authorizer_appid": authorizer_appid},
        )
    except WechatComponentUnavailable:
        return {}
    info = data.get("authorizer_info")
    return info if isinstance(info, dict) else {}


@transaction.atomic
def complete_wechat_authorization(*, session_id, authorization_code: str) -> PlatformAccount:
    config = component_config()
    if config is None:
        raise WechatComponentUnavailable("wechat_component_not_configured")
    try:
        session = PlatformAuthorizationSession.objects.select_for_update().select_related("account").get(
            pk=session_id,
            platform_key="wechat",
        )
    except PlatformAuthorizationSession.DoesNotExist as exc:
        raise WechatComponentUnavailable("authorization_session_missing") from exc
    if session.status == PlatformAuthorizationSession.Status.SUCCEEDED and session.account is not None:
        return session.account
    if session.expires_at <= timezone.now():
        raise WechatComponentUnavailable("authorization_timeout")
    data = _api_post(
        f"https://api.weixin.qq.com/cgi-bin/component/api_query_auth?component_access_token={quote(component_access_token())}",
        {"component_appid": config.app_id, "authorization_code": authorization_code},
    )
    auth = data.get("authorization_info")
    if not isinstance(auth, dict):
        raise WechatComponentUnavailable("wechat_component_invalid_response")
    authorizer_appid = str(auth.get("authorizer_appid") or "")
    access_token = str(auth.get("authorizer_access_token") or "")
    refresh_token = str(auth.get("authorizer_refresh_token") or "")
    expires_in = int(auth.get("expires_in") or 7200)
    if not authorizer_appid or not access_token or not refresh_token:
        raise WechatComponentUnavailable("wechat_component_invalid_response")
    expires_at = timezone.now() + timedelta(seconds=max(300, expires_in))
    info = _authorizer_info(authorizer_appid)
    display_name = str(info.get("nick_name") or info.get("user_name") or "微信公众号")[:255]
    return complete_authorization_session(
        session=session,
        secret_payload={
            "access_token": access_token,
            "refresh_token": refresh_token,
            "app_id": authorizer_appid,
            "component_managed": True,
            "expires_at": expires_at.isoformat(),
        },
        display_name=display_name,
        external_account_id=authorizer_appid,
        session_expires_at=expires_at,
    )


@transaction.atomic
def refresh_authorizer_account(account: PlatformAccount) -> bool:
    config = component_config()
    if config is None or account.platform_key != "wechat" or account.status != PlatformAccount.Status.CONNECTED:
        return False
    try:
        secret = decrypt_secret(account.secret_ciphertext)
    except PublishingCredentialError:
        return False
    if not secret.get("component_managed") or not secret.get("refresh_token") or not secret.get("app_id"):
        return False
    data = _api_post(
        f"https://api.weixin.qq.com/cgi-bin/component/api_authorizer_token?component_access_token={quote(component_access_token())}",
        {
            "component_appid": config.app_id,
            "authorizer_appid": secret["app_id"],
            "authorizer_refresh_token": secret["refresh_token"],
        },
    )
    access_token = str(data.get("authorizer_access_token") or "")
    refresh_token = str(data.get("authorizer_refresh_token") or secret["refresh_token"])
    expires_in = int(data.get("expires_in") or 7200)
    if not access_token:
        return False
    expires_at = timezone.now() + timedelta(seconds=max(300, expires_in))
    secret.update(
        {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at.isoformat(),
        }
    )
    account.secret_ciphertext = encrypt_secret(secret)
    account.session_expires_at = expires_at
    account.last_checked_at = timezone.now()
    account.last_error_code = ""
    account.credential_version += 1
    account.save(
        update_fields=(
            "secret_ciphertext",
            "session_expires_at",
            "last_checked_at",
            "last_error_code",
            "credential_version",
            "updated_at",
        )
    )
    return True


@method_decorator(csrf_exempt, name="dispatch")
class WechatComponentEventView(View):
    http_method_names = ["get", "post"]

    def get(self, request: HttpRequest):
        config = component_config()
        if config is None:
            return HttpResponse("not configured", status=503, content_type="text/plain")
        encrypted = request.GET.get("echostr", "")
        timestamp = request.GET.get("timestamp", "")
        nonce = request.GET.get("nonce", "")
        signature = request.GET.get("msg_signature", "")
        if not _verify_signature(config, signature, timestamp, nonce, encrypted):
            return HttpResponse("invalid", status=403, content_type="text/plain")
        try:
            echo = decrypt_component_message(config, encrypted)
        except WechatComponentUnavailable:
            return HttpResponse("invalid", status=400, content_type="text/plain")
        return HttpResponse(echo, content_type="text/plain")

    def post(self, request: HttpRequest):
        config = component_config()
        if config is None:
            return HttpResponse("not configured", status=503, content_type="text/plain")
        if len(request.body) > 128 * 1024:
            return HttpResponse("invalid", status=413, content_type="text/plain")
        try:
            outer = request.body.decode("utf-8")
            encrypted = _xml_value(outer, "Encrypt")
        except (UnicodeDecodeError, WechatComponentUnavailable):
            return HttpResponse("invalid", status=400, content_type="text/plain")
        timestamp = request.GET.get("timestamp", "")
        nonce = request.GET.get("nonce", "")
        signature = request.GET.get("msg_signature", "")
        if not _verify_signature(config, signature, timestamp, nonce, encrypted):
            return HttpResponse("invalid", status=403, content_type="text/plain")
        try:
            message = decrypt_component_message(config, encrypted)
            info_type = _xml_value(message, "InfoType")
            if info_type == "component_verify_ticket":
                ticket = _xml_value(message, "ComponentVerifyTicket")
                if ticket:
                    cache.set(_ticket_key(config.app_id), ticket, timeout=24 * 60 * 60)
                    cache.delete(_token_key(config.app_id))
        except WechatComponentUnavailable:
            return HttpResponse("invalid", status=400, content_type="text/plain")
        return HttpResponse("success", content_type="text/plain")


class WechatComponentCallbackView(View):
    http_method_names = ["get"]

    def get(self, request: HttpRequest):
        session_id = request.GET.get("session_id", "")
        auth_code = request.GET.get("auth_code", "")
        if not session_id or not auth_code:
            return HttpResponse("授权信息不完整，请返回显问重新授权。", status=400, content_type="text/plain; charset=utf-8")
        try:
            session_uuid = uuid.UUID(session_id)
            complete_wechat_authorization(session_id=session_uuid, authorization_code=auth_code)
        except (ValueError, WechatComponentUnavailable, PublishingInputError):
            return HttpResponse("本次授权未完成，请返回显问重新尝试。", status=400, content_type="text/plain; charset=utf-8")
        return HttpResponse(
            "<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>授权成功</title>"
            "<body style='font-family:system-ui;padding:40px'><h2>微信公众号授权成功</h2>"
            "<p>可以关闭此窗口并返回显问。</p><script>setTimeout(()=>window.close(),1200)</script></body></html>",
            content_type="text/html; charset=utf-8",
        )
