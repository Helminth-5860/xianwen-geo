from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core import signing
from django.core.cache import cache
from django.db import transaction
from django.db.models import F
from django.http import Http404
from django.utils import timezone

from apps.documents.exceptions import FileStorageUnavailable
from apps.documents.models import DocumentVersion
from apps.documents.storage import storage_provider
from apps.plans.subscription_services import current_subscription
from apps.subjects.subject_services import subject_for_user_or_404
from apps.users.services import client_ip_address

from .models import ReportShare, ReportShareAccessLog, SubjectWhiteLabelConfig
from .reports import create_export, execute_export, full_report_snapshot, report_for_user_or_404


class ShareError(Exception):
    def __init__(self, code: str, *, status: int = 409):
        super().__init__(code)
        self.code = code
        self.status = status


def _entitled(user, key: str) -> bool:
    subscription = current_subscription(user)
    if subscription is None:
        return False
    value = subscription.entitlement_snapshot.get("limits", {}).get(key, False)
    return value is True or value == 1


def _token_digest(token: str) -> str:
    return hmac.new(
        settings.REPORT_SHARE_HMAC_KEY.encode(), token.encode(), hashlib.sha256
    ).hexdigest()


def _ip_digest(request) -> str:
    value = client_ip_address(request)[:64]
    return hmac.new(
        settings.REPORT_SHARE_HMAC_KEY.encode(), f"share-ip:{value}".encode(), hashlib.sha256
    ).hexdigest()


def _document_for_subject(user, subject, document_version_id):
    if document_version_id is None:
        return None
    try:
        return DocumentVersion.objects.select_related("document").get(
            pk=document_version_id,
            document__user=user,
            document__subject=subject,
            detected_file_kind__in=("jpeg", "png", "webp"),
        )
    except DocumentVersion.DoesNotExist as exc:
        raise ShareError("WHITE_LABEL_ASSET_INVALID", status=422) from exc


def default_brand_snapshot() -> dict[str, Any]:
    return {
        "brand_name": "显问 GEO",
        "white_label": False,
        "primary_color": "#1677ff",
        "header_text": "",
        "footer_text": "",
        "contact": "",
        "statement": "",
        "logo_object_key": "",
        "cover_object_key": "",
    }


def brand_snapshot_for_subject(*, user, subject) -> dict[str, Any]:
    if not _entitled(user, "white_label_enabled"):
        return default_brand_snapshot()
    try:
        config = SubjectWhiteLabelConfig.objects.select_related(
            "logo_document_version", "cover_document_version"
        ).get(user=user, subject=subject)
    except SubjectWhiteLabelConfig.DoesNotExist:
        return default_brand_snapshot()
    return {
        "brand_name": config.brand_name,
        "white_label": True,
        "primary_color": config.primary_color,
        "header_text": config.header_text,
        "footer_text": config.footer_text,
        "contact": config.contact,
        "statement": config.statement,
        "logo_object_key": config.logo_document_version.object_key
        if config.logo_document_version
        else "",
        "cover_object_key": config.cover_document_version.object_key
        if config.cover_document_version
        else "",
    }


def white_label_payload(*, user, subject) -> dict[str, Any]:
    enabled = _entitled(user, "white_label_enabled")
    config = SubjectWhiteLabelConfig.objects.filter(user=user, subject=subject).first()
    return {
        "enabled": enabled,
        "uses_default_brand": not enabled or config is None,
        "config": (
            {
                "brand_name": config.brand_name,
                "logo_document_version_id": str(config.logo_document_version_id)
                if config.logo_document_version_id
                else None,
                "cover_document_version_id": str(config.cover_document_version_id)
                if config.cover_document_version_id
                else None,
                "primary_color": config.primary_color,
                "header_text": config.header_text,
                "footer_text": config.footer_text,
                "contact": config.contact,
                "statement": config.statement,
                "version": config.version,
            }
            if config
            else None
        ),
        "effective_brand": _public_brand(brand_snapshot_for_subject(user=user, subject=subject)),
    }


@transaction.atomic
def save_white_label(*, user, subject_id, expected_version, **values):
    subject = subject_for_user_or_404(user=user, subject_id=subject_id, lock=True)
    if not _entitled(user, "white_label_enabled"):
        raise ShareError("WHITE_LABEL_NOT_ENTITLED", status=403)
    logo = _document_for_subject(user, subject, values.pop("logo_document_version_id"))
    cover = _document_for_subject(user, subject, values.pop("cover_document_version_id"))
    config = (
        SubjectWhiteLabelConfig.objects.select_for_update()
        .filter(user=user, subject=subject)
        .first()
    )
    if config is None:
        if expected_version != 0:
            raise ShareError("WHITE_LABEL_VERSION_CONFLICT")
        return SubjectWhiteLabelConfig.objects.create(
            user=user,
            subject=subject,
            logo_document_version=logo,
            cover_document_version=cover,
            **values,
        )
    if config.version != expected_version:
        raise ShareError("WHITE_LABEL_VERSION_CONFLICT")
    for key, value in values.items():
        setattr(config, key, value)
    config.logo_document_version = logo
    config.cover_document_version = cover
    config.version += 1
    config.save()
    return config


def _public_brand(snapshot: dict[str, Any]) -> dict[str, Any]:
    data = {key: value for key, value in snapshot.items() if not key.endswith("_object_key")}
    for asset in ("logo", "cover"):
        key = snapshot.get(f"{asset}_object_key", "")
        try:
            data[f"{asset}_url"] = (
                storage_provider().create_download_url(
                    key=key,
                    filename=f"share-{asset}",
                    content_type="application/octet-stream",
                )
                if key
                else None
            )
        except FileStorageUnavailable:
            data[f"{asset}_url"] = None
    return data


@transaction.atomic
def create_report_share(*, user, report_id, password, expires_in_days):
    if not _entitled(user, "report_share_enabled"):
        raise ShareError("REPORT_SHARE_NOT_ENTITLED", status=403)
    report = report_for_user_or_404(user=user, report_id=report_id)
    if expires_in_days is not None and expires_in_days > settings.REPORT_SHARE_MAX_EXPIRY_DAYS:
        raise ShareError("REPORT_SHARE_EXPIRY_INVALID", status=422)
    token = secrets.token_urlsafe(32)
    snapshot = full_report_snapshot(report)
    brand = brand_snapshot_for_subject(user=user, subject=report.subject)
    share = ReportShare.objects.create(
        report=report,
        user=user,
        subject=report.subject,
        token_digest=_token_digest(token),
        report_snapshot=snapshot,
        report_snapshot_digest=hashlib.sha256(
            __import__("json")
            .dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            .encode()
        ).hexdigest(),
        brand_snapshot=brand,
        password_hash=make_password(password) if password else "",
        expires_at=(timezone.now() + timedelta(days=expires_in_days)) if expires_in_days else None,
    )
    return share, token


def share_payload(share: ReportShare) -> dict[str, Any]:
    now = timezone.now()
    return {
        "id": str(share.pk),
        "report_id": str(share.report_id),
        "subject_id": str(share.subject_id),
        "password_required": bool(share.password_hash),
        "expires_at": share.expires_at,
        "closed_at": share.closed_at,
        "status": "closed"
        if share.closed_at
        else "expired"
        if share.expires_at and share.expires_at <= now
        else "active",
        "access_count": share.access_count,
        "last_accessed_at": share.last_accessed_at,
        "created_at": share.created_at,
    }


@transaction.atomic
def close_report_share(*, user, share_id):
    try:
        share = ReportShare.objects.select_for_update().get(pk=share_id, user=user)
    except ReportShare.DoesNotExist as exc:
        raise Http404 from exc
    if share.closed_at is None:
        share.closed_at = timezone.now()
        share.save(update_fields=("closed_at",))
    return share


def _share_by_token(token: str) -> ReportShare:
    if not isinstance(token, str) or not 32 <= len(token) <= 100:
        raise Http404
    try:
        return ReportShare.objects.select_related("report", "subject", "user").get(
            token_digest=_token_digest(token)
        )
    except ReportShare.DoesNotExist as exc:
        raise Http404 from exc


def _status(share: ReportShare) -> str:
    if share.closed_at is not None:
        return "closed"
    if share.expires_at is not None and share.expires_at <= timezone.now():
        return "expired"
    return "active"


def _log(share, request, result):
    ReportShareAccessLog.objects.create(
        share=share,
        ip_digest=_ip_digest(request),
        user_agent=str(request.META.get("HTTP_USER_AGENT", ""))[:300],
        result=result,
    )


def _cookie_name(share) -> str:
    return f"xw_report_share_{share.pk.hex}"


def _session_valid(share, request) -> bool:
    if not share.password_hash:
        return True
    signed = request.COOKIES.get(_cookie_name(share), "")
    if not signed:
        return False
    try:
        value = signing.loads(
            signed,
            salt="report-share-session-v1",
            max_age=settings.REPORT_SHARE_SESSION_TTL_SECONDS,
        )
    except signing.BadSignature:
        return False
    return value == {
        "share_id": str(share.pk),
        "password_digest": hashlib.sha256(share.password_hash.encode()).hexdigest(),
    }


def public_share_payload(*, token, request):
    share = _share_by_token(token)
    status = _status(share)
    if status != "active":
        _log(share, request, status)
        raise ShareError(f"REPORT_SHARE_{status.upper()}", status=410)
    if not _session_valid(share, request):
        _log(share, request, "password_required")
        return share, {
            "password_required": True,
            "unlocked": False,
            "summary": {
                "report_id": str(share.report_id),
                "generated_at": share.report_snapshot.get("report", {}).get("generated_at"),
                "brand": _public_brand(share.brand_snapshot),
            },
        }
    ReportShare.objects.filter(pk=share.pk).update(
        access_count=F("access_count") + 1, last_accessed_at=timezone.now()
    )
    _log(share, request, "success")
    return share, {
        "password_required": bool(share.password_hash),
        "unlocked": True,
        "report": share.report_snapshot,
        "brand": _public_brand(share.brand_snapshot),
        "pdf_available": True,
    }


def unlock_report_share(*, token, password, request):
    share = _share_by_token(token)
    status = _status(share)
    if status != "active":
        _log(share, request, status)
        raise ShareError(f"REPORT_SHARE_{status.upper()}", status=410)
    if not share.password_hash:
        raise ShareError("REPORT_SHARE_PASSWORD_NOT_REQUIRED", status=422)
    limiter = f"report-share-unlock:{share.pk}:{_ip_digest(request)}"
    attempts = cache.get(limiter, 0)
    if attempts >= 10:
        _log(share, request, "rate_limited")
        raise ShareError("REPORT_SHARE_UNLOCK_RATE_LIMITED", status=429)
    if not check_password(password, share.password_hash):
        cache.set(limiter, attempts + 1, timeout=900)
        _log(share, request, "password_failed")
        raise ShareError("REPORT_SHARE_PASSWORD_INVALID", status=403)
    cache.delete(limiter)
    _log(share, request, "unlocked")
    value = signing.dumps(
        {
            "share_id": str(share.pk),
            "password_digest": hashlib.sha256(share.password_hash.encode()).hexdigest(),
        },
        salt="report-share-session-v1",
        compress=True,
    )
    return share, value


def public_share_pdf(*, token, request):
    share = _share_by_token(token)
    if _status(share) != "active":
        _log(share, request, _status(share))
        raise ShareError("REPORT_SHARE_UNAVAILABLE", status=410)
    if not _session_valid(share, request):
        _log(share, request, "password_required")
        raise ShareError("REPORT_SHARE_PASSWORD_REQUIRED", status=403)
    export = create_export(report=share.report, user=share.user, format="pdf")
    export.brand_snapshot = share.brand_snapshot
    export.save(update_fields=("brand_snapshot",))
    execute_export(export_id=export.pk)
    export.refresh_from_db()
    if export.status != "succeeded":
        raise ShareError("REPORT_SHARE_PDF_UNAVAILABLE", status=503)
    _log(share, request, "pdf")
    return storage_provider().create_download_url(
        key=export.object_key,
        filename=f"geo-report-{share.report_id}.pdf",
        content_type="application/pdf",
    )
