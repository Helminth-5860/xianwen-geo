from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.http import Http404

from apps.admin_rbac.scopes import scoped_customers
from apps.subjects.models import Subject

from .catalog import paid_media_catalog
from .exceptions import (
    PaidMediaBusinessError,
    PaidMediaInputInvalid,
    PaidMediaStateConflict,
    PaidMediaVersionConflict,
)
from .models import PaidMediaInquiry


@dataclass(frozen=True)
class CreateInquiryResult:
    inquiry: PaidMediaInquiry
    replayed: bool


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _idempotency_digest(*, user_id, subject_id, raw_key: str | None) -> str:
    key = (raw_key or "").strip()
    if not key or len(key) > 200 or any(ord(char) < 33 or ord(char) > 126 for char in key):
        raise PaidMediaInputInvalid(
            "PAID_MEDIA_IDEMPOTENCY_KEY_REQUIRED",
            "请求已失效，请刷新页面后重试。",
        )
    namespace = hmac.new(
        settings.SECRET_KEY.encode(),
        f"paid-media-inquiry:{subject_id}:v1".encode(),
        hashlib.sha256,
    ).digest()
    return hmac.new(namespace, f"{user_id}:{key}".encode(), hashlib.sha256).hexdigest()


def subject_for_user(user, subject_id, *, lock: bool = False) -> Subject:
    query = Subject.objects.filter(
        pk=subject_id,
        user=user,
        user__tenant_id=user.tenant_id,
        status=Subject.Status.ACTIVE,
    )
    if lock:
        query = query.select_for_update(of=("self",))
    try:
        return query.get()
    except Subject.DoesNotExist as exc:
        raise Http404 from exc


def _normalized_ids(media_ids: list[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_id in media_ids:
        item_id = raw_id.strip()
        if not item_id or item_id in seen:
            continue
        normalized.append(item_id)
        seen.add(item_id)
    if not normalized:
        raise PaidMediaInputInvalid("PAID_MEDIA_SELECTION_REQUIRED", "请至少选择一家媒体。")
    if len(normalized) > 200:
        raise PaidMediaInputInvalid("PAID_MEDIA_SELECTION_TOO_LARGE", "每次最多选择 200 家媒体。")
    return tuple(normalized)


@transaction.atomic
def create_inquiry(
    *,
    user,
    subject_id,
    media_ids: list[str],
    idempotency_key: str | None,
    request_id,
) -> CreateInquiryResult:
    subject = subject_for_user(user, subject_id, lock=True)
    selected_ids = _normalized_ids(media_ids)
    catalog = paid_media_catalog()
    try:
        selected = tuple(catalog.by_id[item_id] for item_id in selected_ids)
    except KeyError as exc:
        raise PaidMediaInputInvalid(
            "PAID_MEDIA_SELECTION_STALE",
            "所选媒体信息已发生变化，请刷新目录后重新选择。",
        ) from exc
    request_digest = _digest(
        {
            "subject_id": str(subject.pk),
            "media_ids": sorted(selected_ids),
        }
    )
    key_digest = _idempotency_digest(
        user_id=user.pk,
        subject_id=subject.pk,
        raw_key=idempotency_key,
    )
    existing = PaidMediaInquiry.objects.filter(idempotency_key_digest=key_digest).first()
    if existing is not None:
        if (
            existing.user_id != user.pk
            or existing.tenant_id != user.tenant_id
            or existing.subject_id != subject.pk
            or existing.request_digest != request_digest
        ):
            raise PaidMediaBusinessError(
                "PAID_MEDIA_IDEMPOTENCY_CONFLICT",
                "请求内容已发生变化，请刷新页面后重试。",
                status=409,
            )
        return CreateInquiryResult(existing, True)
    total_cents = sum(item.price_cents for item in selected)
    inquiry = PaidMediaInquiry.objects.create(
        id=uuid.uuid4(),
        user=user,
        tenant_id=user.tenant_id,
        subject=subject,
        selected_media=[item.inquiry_snapshot() for item in selected],
        item_count=len(selected),
        total_price=Decimal(total_cents) / Decimal(100),
        idempotency_key_digest=key_digest,
        request_digest=request_digest,
        request_id=request_id,
    )
    return CreateInquiryResult(inquiry, False)


def inquiry_for_user(*, user, inquiry_id, subject_id=None, lock: bool = False):
    query = PaidMediaInquiry.objects.select_related("subject", "subject__current_version").filter(
        pk=inquiry_id,
        user=user,
        tenant_id=user.tenant_id,
        subject__user=user,
        subject__user__tenant_id=user.tenant_id,
    )
    if subject_id is not None:
        query = query.filter(subject_id=subject_id)
    if lock:
        query = query.select_for_update(of=("self",))
    try:
        return query.get()
    except PaidMediaInquiry.DoesNotExist as exc:
        raise Http404 from exc


@transaction.atomic
def cancel_inquiry(*, user, inquiry_id, subject_id=None) -> PaidMediaInquiry:
    if subject_id is not None:
        subject_for_user(user, subject_id)
    inquiry = inquiry_for_user(
        user=user,
        inquiry_id=inquiry_id,
        subject_id=subject_id,
        lock=True,
    )
    if inquiry.status != PaidMediaInquiry.Status.PENDING:
        raise PaidMediaStateConflict("只有待处理的申请可以取消。")
    inquiry.status = PaidMediaInquiry.Status.CANCELLED
    inquiry.version += 1
    inquiry.save(update_fields=("status", "version", "updated_at"))
    return inquiry


def scoped_admin_inquiries(user, admin_context):
    customer_ids = scoped_customers(user, admin_context).values("pk")
    return PaidMediaInquiry.objects.filter(user_id__in=customer_ids).select_related(
        "user", "subject", "subject__current_version"
    )


def admin_inquiry_or_404(user, admin_context, inquiry_id, *, lock: bool = False):
    query = scoped_admin_inquiries(user, admin_context)
    if lock:
        query = query.select_for_update(of=("self",))
    try:
        return query.get(pk=inquiry_id)
    except PaidMediaInquiry.DoesNotExist as exc:
        raise Http404 from exc


ADMIN_STATUS_TRANSITIONS = {
    PaidMediaInquiry.Status.PENDING: {
        PaidMediaInquiry.Status.CONTACTED,
        PaidMediaInquiry.Status.CANCELLED,
        PaidMediaInquiry.Status.COMPLETED,
    },
    PaidMediaInquiry.Status.CONTACTED: {
        PaidMediaInquiry.Status.CANCELLED,
        PaidMediaInquiry.Status.COMPLETED,
    },
    PaidMediaInquiry.Status.CANCELLED: set(),
    PaidMediaInquiry.Status.COMPLETED: set(),
}


@transaction.atomic
def update_inquiry_status(
    *, user, admin_context, inquiry_id, status: str, expected_version: int
) -> PaidMediaInquiry:
    inquiry = admin_inquiry_or_404(user, admin_context, inquiry_id, lock=True)
    if inquiry.version != expected_version:
        raise PaidMediaVersionConflict
    if status not in ADMIN_STATUS_TRANSITIONS[inquiry.status]:
        raise PaidMediaStateConflict
    inquiry.status = status
    inquiry.version += 1
    inquiry.save(update_fields=("status", "version", "updated_at"))
    return inquiry
