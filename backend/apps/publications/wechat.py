from __future__ import annotations

import html
import time
from dataclasses import dataclass

import httpx

from apps.documents.storage import storage_provider

from .models import PublicationTarget


class WeChatCredentialError(RuntimeError):
    pass


class WeChatPublishError(RuntimeError):
    pass


@dataclass(frozen=True)
class WeChatPublishResult:
    status: str
    external_post_id: str = ""
    public_url: str = ""


def _json(response: httpx.Response) -> dict:
    try:
        value = response.json()
    except Exception as exc:
        raise WeChatPublishError("invalid platform response") from exc
    if not isinstance(value, dict):
        raise WeChatPublishError("invalid platform response")
    return value


def _access_token(credentials: dict) -> str:
    app_id = str(credentials.get("app_id", "")).strip()
    app_secret = str(credentials.get("app_secret", "")).strip()
    if not app_id or not app_secret:
        raise WeChatCredentialError("missing official credentials")
    with httpx.Client(timeout=15.0) as client:
        response = client.get(
            "https://api.weixin.qq.com/cgi-bin/token",
            params={"grant_type": "client_credential", "appid": app_id, "secret": app_secret},
        )
    data = _json(response)
    token = str(data.get("access_token", "")).strip()
    if not token:
        raise WeChatCredentialError(str(data.get("errcode", "credential rejected")))
    return token


def validate_wechat_credentials(credentials: dict) -> dict:
    _access_token(credentials)
    return {"validated": True}


def _cover_bytes(target: PublicationTarget):
    visual = (
        target.job.visuals.select_related("image")
        .filter(target__isnull=True, role="cover")
        .order_by("ordinal", "created_at")
        .first()
    )
    if visual is None:
        raise WeChatPublishError("cover required")
    image = visual.image
    with storage_provider().open_object(image.object_key) as source:
        data = source.read()
    if not data:
        raise WeChatPublishError("cover unavailable")
    extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(
        image.mime_type, "jpg"
    )
    return data, image.mime_type, f"cover.{extension}"


def _upload_cover(token: str, target: PublicationTarget) -> str:
    data, mime, filename = _cover_bytes(target)
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            "https://api.weixin.qq.com/cgi-bin/material/add_material",
            params={"access_token": token, "type": "thumb"},
            files={"media": (filename, data, mime)},
        )
    payload = _json(response)
    media_id = str(payload.get("media_id", "")).strip()
    if not media_id:
        raise WeChatPublishError(f"cover upload failed:{payload.get('errcode', '')}")
    return media_id


def _article_html(content: str) -> str:
    paragraphs = [value.strip() for value in content.replace("\r", "").split("\n") if value.strip()]
    return "".join(f"<p>{html.escape(value)}</p>" for value in paragraphs)


def _add_draft(token: str, target: PublicationTarget, thumb_media_id: str) -> str:
    payload = target.payload_snapshot or {}
    title = str(payload.get("title", "")).strip()[:64]
    content = str(payload.get("content", "")).strip()
    if not title or not content:
        raise WeChatPublishError("content unavailable")
    request_body = {
        "articles": [
            {
                "title": title,
                "author": "",
                "digest": content.replace("\n", " ")[:120],
                "content": _article_html(content),
                "content_source_url": "",
                "thumb_media_id": thumb_media_id,
                "need_open_comment": 0,
                "only_fans_can_comment": 0,
            }
        ]
    }
    with httpx.Client(timeout=20.0) as client:
        response = client.post(
            "https://api.weixin.qq.com/cgi-bin/draft/add",
            params={"access_token": token},
            json=request_body,
        )
    data = _json(response)
    media_id = str(data.get("media_id", "")).strip()
    if not media_id:
        raise WeChatPublishError(f"draft failed:{data.get('errcode', '')}")
    return media_id


def _submit_publish(token: str, media_id: str) -> str:
    with httpx.Client(timeout=20.0) as client:
        response = client.post(
            "https://api.weixin.qq.com/cgi-bin/freepublish/submit",
            params={"access_token": token},
            json={"media_id": media_id},
        )
    data = _json(response)
    publish_id = str(data.get("publish_id", "")).strip()
    if not publish_id:
        raise WeChatPublishError(f"publish submit failed:{data.get('errcode', '')}")
    return publish_id


def check_wechat_publish(credentials: dict, publish_id: str) -> WeChatPublishResult:
    token = _access_token(credentials)
    with httpx.Client(timeout=20.0) as client:
        response = client.post(
            "https://api.weixin.qq.com/cgi-bin/freepublish/get",
            params={"access_token": token},
            json={"publish_id": publish_id},
        )
    data = _json(response)
    status = data.get("publish_status")
    if status == 1:
        return WeChatPublishResult(status="pending", external_post_id=publish_id)
    if status != 0:
        raise WeChatPublishError(f"publish failed:{status}:{data.get('fail_idx', '')}")
    detail = data.get("article_detail") or {}
    items = detail.get("item") or []
    public_url = ""
    if isinstance(items, list) and items and isinstance(items[0], dict):
        public_url = str(items[0].get("article_url") or items[0].get("url") or "")
    return WeChatPublishResult(
        status="published", external_post_id=publish_id, public_url=public_url
    )


def publish_wechat_target(target: PublicationTarget, credentials: dict) -> WeChatPublishResult:
    if target.external_post_id:
        return check_wechat_publish(credentials, target.external_post_id)
    token = _access_token(credentials)
    thumb_media_id = _upload_cover(token, target)
    draft_id = _add_draft(token, target, thumb_media_id)
    publish_id = _submit_publish(token, draft_id)
    for _ in range(4):
        time.sleep(2)
        result = check_wechat_publish(credentials, publish_id)
        if result.status == "published":
            return result
    return WeChatPublishResult(status="pending", external_post_id=publish_id)
