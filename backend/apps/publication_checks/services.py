from __future__ import annotations

import re
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from apps.subjects.subject_services import subject_for_user_or_404
from apps.web_sources.exceptions import (
    WebSourceContentTooLarge,
    WebSourceContentUnsupported,
    WebSourceError,
    WebSourceTransientError,
    WebSourceUrlInvalid,
    WebSourceUrlNotAllowed,
)
from apps.web_sources.parser import parse_response

from .models import PublicationVerificationCheck
from .network import PublicationProbeResult, probe_publication_url

_NOT_FOUND_PATTERNS = (
    "not found",
    "page not found",
    "页面不存在",
    "内容不存在",
    "文章不存在",
    "文章已删除",
    "内容已删除",
    "该内容已删除",
    "链接已失效",
)
_CHALLENGE_PATTERNS = (
    "captcha",
    "cloudflare",
    "access denied",
    "verify you are human",
    "security check",
    "登录后查看",
    "请先登录",
    "验证码",
    "人机验证",
    "访问受限",
)
_SPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class PublicationAssessment:
    status: str
    title: str
    message: str
    safe_failure_code: str


def _contains_any(value: str, patterns: tuple[str, ...]) -> bool:
    lowered = value.lower()
    return any(pattern in lowered for pattern in patterns)


def _assess_probe(probe: PublicationProbeResult) -> PublicationAssessment:
    status = probe.status
    if status in {404, 410}:
        return PublicationAssessment(
            PublicationVerificationCheck.Status.FAILED,
            "",
            "目标页面不存在或已经失效。",
            f"HTTP_{status}",
        )
    if status in {401, 403, 407, 408, 423, 425, 429} or status >= 500:
        return PublicationAssessment(
            PublicationVerificationCheck.Status.UNKNOWN,
            "",
            "目标网站限制或暂时无法完成自动访问，当前无法确认发布状态。",
            f"HTTP_{status}",
        )
    if 400 <= status < 500:
        return PublicationAssessment(
            PublicationVerificationCheck.Status.FAILED,
            "",
            f"目标页面返回 HTTP {status}，未检测到正常公开页面。",
            f"HTTP_{status}",
        )
    if not 200 <= status < 300:
        return PublicationAssessment(
            PublicationVerificationCheck.Status.UNKNOWN,
            "",
            f"目标页面返回 HTTP {status}，当前无法确认发布状态。",
            f"HTTP_{status}",
        )

    media_type = probe.content_type.split(";", 1)[0].strip().lower()
    if media_type not in {"text/html", "text/plain"}:
        return PublicationAssessment(
            PublicationVerificationCheck.Status.UNKNOWN,
            "",
            "页面可以访问，但返回的内容类型不是可识别的公开文章页面。",
            "CONTENT_TYPE_UNSUPPORTED",
        )

    try:
        title, text, _, _ = parse_response(
            body=probe.body,
            media_type=media_type,
            content_type=probe.content_type,
        )
    except WebSourceError:
        return PublicationAssessment(
            PublicationVerificationCheck.Status.UNKNOWN,
            "",
            "页面可以访问，但暂时无法识别页面正文。",
            "CONTENT_PARSE_UNAVAILABLE",
        )

    normalized = _SPACE.sub(" ", f"{title} {text[:1200]}").strip()
    if _contains_any(normalized, _CHALLENGE_PATTERNS):
        return PublicationAssessment(
            PublicationVerificationCheck.Status.UNKNOWN,
            title[:500],
            "页面存在登录、验证码或访问限制，当前无法自动确认发布状态。",
            "ACCESS_CHALLENGE",
        )
    if _contains_any(normalized, _NOT_FOUND_PATTERNS):
        return PublicationAssessment(
            PublicationVerificationCheck.Status.FAILED,
            title[:500],
            "页面可访问，但页面内容显示文章不存在、已删除或链接已失效。",
            "SOFT_NOT_FOUND",
        )

    meaningful_text = _SPACE.sub(" ", text).strip()
    if title.strip() or len(meaningful_text) >= 80:
        return PublicationAssessment(
            PublicationVerificationCheck.Status.PUBLISHED,
            title[:500],
            "页面已公开可访问，并识别到有效标题或正文内容。",
            "",
        )
    return PublicationAssessment(
        PublicationVerificationCheck.Status.UNKNOWN,
        title[:500],
        "页面可以访问，但有效文章内容不足，当前无法确认是否已成功发布。",
        "CONTENT_NOT_CONFIRMED",
    )


def _hostname(value: str) -> str:
    try:
        return (urlsplit(value).hostname or "")[:255]
    except ValueError:
        return ""


def create_publication_verification(*, user, subject_id, url):
    subject = subject_for_user_or_404(user=user, subject_id=subject_id)
    started = time.monotonic()
    final_url = url
    http_status = None
    title = ""
    status = PublicationVerificationCheck.Status.UNKNOWN
    message = "当前暂时无法判断。"
    code = "PUBLICATION_CHECK_UNAVAILABLE"

    try:
        probe = probe_publication_url(url)
        final_url = probe.final_url
        http_status = probe.status
        assessment = _assess_probe(probe)
        status = assessment.status
        title = assessment.title
        message = assessment.message
        code = assessment.safe_failure_code
    except (WebSourceUrlInvalid, WebSourceUrlNotAllowed):
        status = PublicationVerificationCheck.Status.FAILED
        message = "请输入可公开访问的 HTTP 或 HTTPS 文章链接。"
        code = "PUBLIC_URL_NOT_ALLOWED"
    except WebSourceTransientError:
        status = PublicationVerificationCheck.Status.UNKNOWN
        message = "目标网站当前连接超时或暂时不可用，请稍后重试。"
        code = "TARGET_TEMPORARILY_UNAVAILABLE"
    except (WebSourceContentTooLarge, WebSourceContentUnsupported):
        status = PublicationVerificationCheck.Status.UNKNOWN
        message = "目标页面返回了暂时无法识别的内容，当前无法确认发布状态。"
        code = "CONTENT_NOT_SUPPORTED"
    except WebSourceError:
        status = PublicationVerificationCheck.Status.UNKNOWN
        message = "当前无法自动确认该页面的发布状态。"
        code = "PUBLICATION_CHECK_UNAVAILABLE"

    elapsed_ms = max(0, round((time.monotonic() - started) * 1000))
    return PublicationVerificationCheck.objects.create(
        user=user,
        subject=subject,
        requested_url=url,
        final_url=final_url,
        hostname=_hostname(final_url or url),
        status=status,
        page_title=title,
        http_status=http_status,
        response_time_ms=elapsed_ms,
        result_message=message,
        safe_failure_code=code,
    )


def publication_verification_payload(row: PublicationVerificationCheck) -> dict:
    return {
        "id": str(row.pk),
        "subject_id": str(row.subject_id),
        "requested_url": row.requested_url,
        "final_url": row.final_url,
        "hostname": row.hostname,
        "status": row.status,
        "page_title": row.page_title,
        "http_status": row.http_status,
        "response_time_ms": row.response_time_ms,
        "result_message": row.result_message,
        "safe_failure_code": row.safe_failure_code,
        "checked_at": row.checked_at,
    }
