import hashlib
import hmac
import json
import re
from dataclasses import dataclass

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.admin_rbac.models import AdminProfile
from apps.admin_rbac.scopes import scoped_customers
from apps.users.models import Notification, User
from apps.users.validators import validate_safe_plain_text

from .models import Plan, PlanApplication, PlanApplicationEvent, PlanVersion
from .services import public_plan_summary

IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{16,128}$")


class PlanApplicationError(Exception):
    code = "PLAN_APPLICATION_STATE_CONFLICT"


class PlanApplicationNotEligible(PlanApplicationError):
    code = "PLAN_APPLICATION_NOT_ELIGIBLE"


class PlanApplicationPlanUnavailable(PlanApplicationError):
    code = "PLAN_APPLICATION_PLAN_UNAVAILABLE"


class PlanApplicationAlreadyOpen(PlanApplicationError):
    code = "PLAN_APPLICATION_ALREADY_OPEN"

    def __init__(self, application=None):
        self.application = application


class PlanApplicationStateConflict(PlanApplicationError):
    code = "PLAN_APPLICATION_STATE_CONFLICT"


class PlanApplicationVersionConflict(PlanApplicationError):
    code = "PLAN_APPLICATION_VERSION_CONFLICT"


class PlanApplicationVersionMismatch(PlanApplicationError):
    code = "PLAN_APPLICATION_VERSION_MISMATCH"


class PlanApplicationNoteInvalid(PlanApplicationError):
    code = "PLAN_APPLICATION_NOTE_INVALID"


class IdempotencyKeyRequired(PlanApplicationError):
    code = "IDEMPOTENCY_KEY_REQUIRED"


class IdempotencyConflict(PlanApplicationError):
    code = "IDEMPOTENCY_CONFLICT"


@dataclass(frozen=True)
class CreateApplicationResult:
    application: PlanApplication
    replayed: bool


NOTIFICATION_TEMPLATES = {
    PlanApplicationEvent.EventType.SUBMITTED: (
        Notification.NotificationType.PLAN_APPLICATION_SUBMITTED,
        "套餐申请已提交",
        "你的套餐申请已提交，请等待工作人员联系。",
    ),
    PlanApplicationEvent.EventType.CONTACTED: (
        Notification.NotificationType.PLAN_APPLICATION_CONTACTED,
        "套餐申请已联系",
        "工作人员已联系处理你的套餐申请。",
    ),
    PlanApplicationEvent.EventType.CLOSED: (
        Notification.NotificationType.PLAN_APPLICATION_CLOSED,
        "套餐申请已关闭",
        "你的套餐申请已关闭，如有需要可以重新申请。",
    ),
    PlanApplicationEvent.EventType.CANCELLED: (
        Notification.NotificationType.PLAN_APPLICATION_CANCELLED,
        "套餐申请已取消",
        "你的套餐申请已取消。",
    ),
}


def normalize_user_note(value: str) -> str:
    try:
        return validate_safe_plain_text(
            value, field_label="申请备注", max_length=500, required=False
        )
    except Exception as exc:
        raise PlanApplicationNoteInvalid from exc


def validate_idempotency_key(value: str | None) -> str:
    if not value or not IDEMPOTENCY_KEY_PATTERN.fullmatch(value):
        raise IdempotencyKeyRequired
    return value


def _hmac_digest(label: bytes, value: str) -> str:
    root = hmac.new(
        settings.SECRET_KEY.encode(), b"xianwen:plan-application:v1", hashlib.sha256
    ).digest()
    key = hmac.new(root, label, hashlib.sha256).digest()
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()


def idempotency_digest(value: str) -> str:
    return _hmac_digest(b"idempotency", value)


def request_digest(*, applicant_id, plan_id, plan_version_id, user_note: str) -> str:
    document = {
        "applicant_id": str(applicant_id),
        "plan_id": str(plan_id),
        "plan_version_id": str(plan_version_id),
        "source": PlanApplication.Source.USER_WEB,
        "user_note": user_note,
    }
    encoded = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _hmac_digest(b"request", encoded)


def _ensure_create_eligible(user: User) -> None:
    if (
        user.is_staff
        or user.is_superuser
        or not user.is_active
        or user.account_status != User.AccountStatus.ACTIVE
        or AdminProfile.objects.filter(user=user).exists()
    ):
        raise PlanApplicationNotEligible


def _public_snapshot(plan: Plan, version: PlanVersion) -> dict:
    summary = public_plan_summary(plan)
    return {
        "plan_id": str(plan.pk),
        "plan_version_id": str(version.pk),
        "code": summary["code"],
        "name": summary["name"],
        "description": summary["description"],
        "price_display_mode": summary["price_display_mode"],
        "display_price": summary["display_price"],
        "display_currency": summary["display_currency"],
        "is_trial": summary["is_trial"],
        "version_no": version.version_no,
        "valid_days": summary["valid_days"],
        "benefits": summary["benefits"],
        "models": [
            {"model_key": item["model_key"], "name": item["name"]} for item in summary["models"]
        ],
        "supports_formal_composite": summary["supports_formal_composite"],
    }


def _event_and_notification(*, application, event_type, from_status, actor, request_id):
    notification_type, title, safe_summary = NOTIFICATION_TEMPLATES[event_type]
    event = PlanApplicationEvent.objects.create(
        application=application,
        event_type=event_type,
        from_status=from_status,
        to_status=application.status,
        actor=actor,
        safe_summary=safe_summary,
        request_id=request_id,
    )
    Notification.objects.create(
        recipient=application.applicant,
        notification_type=notification_type,
        title=title,
        safe_summary=safe_summary,
        related_plan_application=application,
    )
    return event


@transaction.atomic
def create_application(
    *,
    applicant: User,
    plan_id,
    plan_version_id,
    user_note: str,
    idempotency_key: str,
    request_id,
) -> CreateApplicationResult:
    _ensure_create_eligible(applicant)
    note = normalize_user_note(user_note)
    key_digest = idempotency_digest(validate_idempotency_key(idempotency_key))
    digest = request_digest(
        applicant_id=applicant.pk,
        plan_id=plan_id,
        plan_version_id=plan_version_id,
        user_note=note,
    )
    existing = PlanApplication.objects.filter(
        applicant=applicant, idempotency_key_digest=key_digest
    ).first()
    if existing:
        if existing.request_digest != digest:
            raise IdempotencyConflict
        return CreateApplicationResult(existing, True)
    try:
        plan = Plan.objects.select_for_update().get(pk=plan_id)
    except Plan.DoesNotExist as exc:
        raise PlanApplicationPlanUnavailable from exc
    if plan.is_trial:
        raise PlanApplicationNotEligible
    if plan.status != Plan.Status.PUBLISHED or plan.current_published_version_id is None:
        raise PlanApplicationPlanUnavailable
    try:
        version = PlanVersion.objects.select_for_update().get(pk=plan_version_id, plan=plan)
    except PlanVersion.DoesNotExist as exc:
        raise PlanApplicationVersionMismatch from exc
    if (
        plan.current_published_version_id != version.pk
        or version.status != PlanVersion.Status.PUBLISHED
        or not version.config_digest
    ):
        raise PlanApplicationVersionMismatch
    existing = PlanApplication.objects.filter(
        applicant=applicant, idempotency_key_digest=key_digest
    ).first()
    if existing:
        if existing.request_digest != digest:
            raise IdempotencyConflict
        return CreateApplicationResult(existing, True)
    opened = PlanApplication.objects.filter(
        applicant=applicant, plan=plan, status__in=PlanApplication.OPEN_STATUSES
    ).first()
    if opened:
        raise PlanApplicationAlreadyOpen(opened)
    try:
        with transaction.atomic():
            application = PlanApplication.objects.create(
                applicant=applicant,
                plan=plan,
                requested_plan_version=version,
                requested_version_no=version.version_no,
                requested_config_digest=version.config_digest,
                public_plan_snapshot=_public_snapshot(plan, version),
                user_note=note,
                idempotency_key_digest=key_digest,
                request_digest=digest,
                request_id=request_id,
            )
    except IntegrityError as exc:
        replay = PlanApplication.objects.filter(
            applicant=applicant, idempotency_key_digest=key_digest
        ).first()
        if replay:
            if replay.request_digest != digest:
                raise IdempotencyConflict from exc
            return CreateApplicationResult(replay, True)
        opened = PlanApplication.objects.filter(
            applicant=applicant, plan=plan, status__in=PlanApplication.OPEN_STATUSES
        ).first()
        raise PlanApplicationAlreadyOpen(opened) from exc
    _event_and_notification(
        application=application,
        event_type=PlanApplicationEvent.EventType.SUBMITTED,
        from_status="",
        actor=applicant,
        request_id=request_id,
    )
    return CreateApplicationResult(application, False)


def user_application_or_404(user: User, application_id, *, lock=False):
    query = PlanApplication.objects.select_related(
        "plan", "requested_plan_version", "applicant"
    ).prefetch_related("events")
    if lock:
        query = query.select_for_update(of=("self",))
    try:
        return query.get(pk=application_id, applicant=user)
    except PlanApplication.DoesNotExist as exc:
        raise NotFound from exc


def scoped_plan_applications(user, context):
    customers = scoped_customers(user, context).values("pk")
    return (
        PlanApplication.objects.filter(applicant_id__in=customers)
        .select_related(
            "applicant",
            "plan",
            "requested_plan_version",
            "applicant__customer_assignment__owner_admin__user",
        )
        .prefetch_related("events")
    )


def scoped_application_or_404(user, context, application_id, *, lock=False):
    query = scoped_plan_applications(user, context)
    if lock:
        query = query.select_for_update(of=("self",))
    try:
        return query.get(pk=application_id)
    except PlanApplication.DoesNotExist as exc:
        raise NotFound from exc


@transaction.atomic
def cancel_application(*, user: User, application_id, expected_version: int, request_id):
    if not user.is_active or user.account_status not in (
        User.AccountStatus.ACTIVE,
        User.AccountStatus.CANCEL_PENDING,
    ):
        raise PlanApplicationNotEligible
    application = user_application_or_404(user, application_id, lock=True)
    if application.version != expected_version:
        raise PlanApplicationVersionConflict
    if application.status not in PlanApplication.OPEN_STATUSES:
        raise PlanApplicationStateConflict
    previous = application.status
    application.status = PlanApplication.Status.CANCELLED
    application.cancelled_at = timezone.now()
    application.version += 1
    application.save(update_fields=["status", "cancelled_at", "version", "updated_at"])
    _event_and_notification(
        application=application,
        event_type=PlanApplicationEvent.EventType.CANCELLED,
        from_status=previous,
        actor=user,
        request_id=request_id,
    )
    return application


@transaction.atomic
def admin_change_application(
    *,
    requester,
    admin_context,
    application_id,
    expected_version: int,
    action: str,
    request_id,
):
    application = scoped_application_or_404(requester, admin_context, application_id, lock=True)
    if application.version != expected_version:
        raise PlanApplicationVersionConflict
    previous = application.status
    now = timezone.now()
    if action == "contact" and previous == PlanApplication.Status.PENDING:
        application.status = PlanApplication.Status.CONTACTED
        application.contacted_at = now
        application.contacted_by = requester
        event_type = PlanApplicationEvent.EventType.CONTACTED
        fields = ["status", "contacted_at", "contacted_by", "version", "updated_at"]
    elif action == "close" and previous in PlanApplication.OPEN_STATUSES:
        application.status = PlanApplication.Status.CLOSED
        application.closed_at = now
        application.closed_by = requester
        event_type = PlanApplicationEvent.EventType.CLOSED
        fields = ["status", "closed_at", "closed_by", "version", "updated_at"]
    else:
        raise PlanApplicationStateConflict
    application.version += 1
    application.save(update_fields=fields)
    _event_and_notification(
        application=application,
        event_type=event_type,
        from_status=previous,
        actor=requester,
        request_id=request_id,
    )
    return application
