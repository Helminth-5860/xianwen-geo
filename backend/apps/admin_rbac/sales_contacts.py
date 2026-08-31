from __future__ import annotations

import hashlib
import io
import uuid
import warnings
from dataclasses import dataclass
from urllib.parse import urlencode

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.urls import reverse
from PIL import Image, UnidentifiedImageError
from rest_framework.exceptions import ValidationError

from apps.documents.storage import storage_provider
from apps.users.commercial import CommercialIdentity

from .audit_services import record_audit_event
from .models import (
    AdminProfile,
    CustomerAssignment,
    SalesContactConfiguration,
)

MAX_QR_CODE_BYTES = 5 * 1024 * 1024
MAX_QR_CODE_DIMENSION = 4096
MAX_QR_CODE_PIXELS = 16_000_000
MEDIA_TOKEN_SALT = "sales-contact-media-v1"
UNCONFIGURED_MESSAGE = "销售联系方式暂未配置，请稍后联系平台客服。"

_IMAGE_FORMATS = {
    "JPEG": ("image/jpeg", "jpg"),
    "PNG": ("image/png", "png"),
    "WEBP": ("image/webp", "webp"),
}


@dataclass(frozen=True)
class ValidatedQrCode:
    data: bytes
    mime_type: str
    extension: str
    sha256: str


def validate_qr_code(uploaded_file) -> ValidatedQrCode:
    try:
        data = uploaded_file.read(MAX_QR_CODE_BYTES + 1)
    except Exception as exc:
        raise ValidationError({"qr_code": ["无法读取二维码图片，请重新选择文件。"]}) from exc
    if not data:
        raise ValidationError({"qr_code": ["二维码图片不能为空。"]})
    if len(data) > MAX_QR_CODE_BYTES:
        raise ValidationError({"qr_code": ["二维码图片不能超过 5MB。"]})

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                detected_format = str(image.format or "").upper()
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                width, height = image.size
    except (Image.DecompressionBombError, Image.DecompressionBombWarning, UnidentifiedImageError):
        raise ValidationError({"qr_code": ["请选择有效的 PNG、JPG 或 WebP 图片。"]}) from None
    except Exception as exc:
        raise ValidationError({"qr_code": ["二维码图片无法通过安全检查。"]}) from exc

    media = _IMAGE_FORMATS.get(detected_format)
    if media is None:
        raise ValidationError({"qr_code": ["仅支持 PNG、JPG 或 WebP 图片。"]})
    if width < 64 or height < 64:
        raise ValidationError({"qr_code": ["二维码图片尺寸过小，请选择清晰图片。"]})
    if (
        width > MAX_QR_CODE_DIMENSION
        or height > MAX_QR_CODE_DIMENSION
        or width * height > MAX_QR_CODE_PIXELS
    ):
        raise ValidationError({"qr_code": ["二维码图片尺寸过大，请压缩后重试。"]})

    mime_type, extension = media
    return ValidatedQrCode(
        data=data,
        mime_type=mime_type,
        extension=extension,
        sha256=hashlib.sha256(data).hexdigest(),
    )


def _scope_for_admin(context) -> tuple[str, AdminProfile | None]:
    if context.identity == CommercialIdentity.SUPER_ADMIN:
        return SalesContactConfiguration.Scope.GLOBAL, None
    return SalesContactConfiguration.Scope.AGENT, context.profile


def get_admin_configuration(context) -> SalesContactConfiguration | None:
    scope, owner = _scope_for_admin(context)
    return SalesContactConfiguration.objects.filter(scope=scope, owner_admin=owner).first()


def _snapshot(config: SalesContactConfiguration) -> dict[str, object]:
    return {
        "scope": config.scope,
        "agent_id": str(config.owner_admin_id) if config.owner_admin_id else None,
        "enabled": config.enabled,
        "file_reference": config.object_key or None,
        "file_sha256": config.sha256 or None,
        "version": config.version,
    }


def _audit_change(
    *,
    request,
    config: SalesContactConfiguration,
    event_type: str,
    before: dict[str, object],
) -> None:
    record_audit_event(
        request=request,
        category="sales_contact",
        action_key=event_type,
        outcome="updated",
        actor=request.user,
        requester=request.user,
        subject=config.owner_admin.user if config.owner_admin_id else None,
        target_type="sales_contact",
        target_id=config.pk,
        safe_before=before,
        safe_after=_snapshot(config),
    )


@transaction.atomic
def save_qr_code(*, context, request, qr_code: ValidatedQrCode, enabled: bool):
    scope, owner = _scope_for_admin(context)
    config, _ = SalesContactConfiguration.objects.get_or_create(
        scope=scope,
        owner_admin=owner,
        defaults={"enabled": False},
    )
    config = SalesContactConfiguration.objects.select_for_update().get(pk=config.pk)
    before = _snapshot(config)

    owner_segment = str(owner.pk) if owner is not None else "global"
    object_key = (
        f"system/sales-contact/{scope}/{owner_segment}/"
        f"{uuid.uuid4().hex}.{qr_code.extension}"
    )
    storage_provider().put_system_stream(
        key=object_key,
        stream=io.BytesIO(qr_code.data),
        content_type=qr_code.mime_type,
        size=len(qr_code.data),
        sha256=qr_code.sha256,
    )

    config.object_key = object_key
    config.mime_type = qr_code.mime_type
    config.size_bytes = len(qr_code.data)
    config.sha256 = qr_code.sha256
    config.enabled = enabled
    config.updated_by = request.user
    config.version += 1
    config.full_clean()
    config.save(
        update_fields=(
            "object_key",
            "mime_type",
            "size_bytes",
            "sha256",
            "enabled",
            "updated_by",
            "version",
            "updated_at",
        )
    )
    _audit_change(
        request=request,
        config=config,
        event_type=(
            "sales_contact_qr_replaced" if before["file_reference"] else "sales_contact_qr_set"
        ),
        before=before,
    )
    return config


@transaction.atomic
def set_configuration_enabled(*, context, request, enabled: bool):
    scope, owner = _scope_for_admin(context)
    config = (
        SalesContactConfiguration.objects.select_for_update()
        .filter(scope=scope, owner_admin=owner)
        .first()
    )
    if config is None or not config.object_key:
        if enabled:
            raise ValidationError({"enabled": ["请先上传销售微信二维码。"]})
        return None
    if config.enabled == enabled:
        return config

    before = _snapshot(config)
    config.enabled = enabled
    config.updated_by = request.user
    config.version += 1
    config.full_clean()
    config.save(update_fields=("enabled", "updated_by", "version", "updated_at"))
    _audit_change(
        request=request,
        config=config,
        event_type="sales_contact_enabled" if enabled else "sales_contact_disabled",
        before=before,
    )
    return config


def resolve_customer_configuration(user) -> SalesContactConfiguration | None:
    assignment = (
        CustomerAssignment.objects.select_related(
            "owner_admin__user",
            "owner_admin__role",
        )
        .filter(customer=user)
        .first()
    )
    if assignment is not None and assignment.owner_admin_id is not None:
        owner = assignment.owner_admin
        owner_is_active = bool(
            owner
            and owner.admin_status == AdminProfile.Status.ACTIVE
            and owner.user.is_active
            and owner.user.is_staff
            and not owner.user.is_superuser
            and owner.role_id is not None
            and owner.role.status == owner.role.Status.ACTIVE
        )
        agent_config = (
            SalesContactConfiguration.objects.filter(
                scope=SalesContactConfiguration.Scope.AGENT,
                owner_admin_id=assignment.owner_admin_id,
                enabled=True,
            )
            .exclude(object_key="")
            .first()
            if owner_is_active
            else None
        )
        if agent_config is not None:
            return agent_config
    return (
        SalesContactConfiguration.objects.filter(
            scope=SalesContactConfiguration.Scope.GLOBAL,
            owner_admin__isnull=True,
            enabled=True,
        )
        .exclude(object_key="")
        .first()
    )


def create_media_token(
    config: SalesContactConfiguration, *, allow_disabled: bool = False
) -> str:
    return signing.dumps(
        {
            "configuration_id": str(config.pk),
            "version": config.version,
            "allow_disabled": allow_disabled,
        },
        salt=MEDIA_TOKEN_SALT,
        compress=True,
    )


def media_url(request, config: SalesContactConfiguration, *, allow_disabled: bool = False) -> str:
    token = create_media_token(config, allow_disabled=allow_disabled)
    path = f"{reverse('sales-contact-media')}?{urlencode({'token': token})}"
    forwarded_proto = str(request.META.get("HTTP_X_FORWARDED_PROTO", "")).split(",", 1)[0]
    if forwarded_proto.strip().lower() == "https":
        return f"https://{request.get_host()}{path}"
    return request.build_absolute_uri(path)


def configuration_from_media_token(token: str) -> SalesContactConfiguration | None:
    try:
        payload = signing.loads(
            token,
            salt=MEDIA_TOKEN_SALT,
            max_age=settings.FILE_DOWNLOAD_URL_TTL,
        )
        configuration_id = uuid.UUID(str(payload["configuration_id"]))
        version = int(payload["version"])
        allow_disabled = payload.get("allow_disabled") is True
    except (KeyError, TypeError, ValueError, signing.BadSignature, signing.SignatureExpired):
        return None

    queryset = SalesContactConfiguration.objects.filter(
        pk=configuration_id,
        version=version,
    ).exclude(object_key="")
    if not allow_disabled:
        queryset = queryset.filter(enabled=True)
    return queryset.first()
