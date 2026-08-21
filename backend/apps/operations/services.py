from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import timedelta

from django.core.cache import cache
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from rest_framework.exceptions import Throttled

from apps.admin_rbac.audit_services import record_audit_event
from apps.admin_rbac.models import CustomerAssignment
from apps.admin_rbac.scopes import scoped_customer_or_404, scoped_customers
from apps.articles.models import Article, ArticleGenerationJob, ArticleModerationReview
from apps.geo.models import GeoDetectionJob, StrategyReport
from apps.images.models import ImageAsset, ImageGenerationJob, ImageModerationReview
from apps.plans.models import Subscription
from apps.subjects.models import Subject
from apps.users.models import User

from .models import (
    Announcement,
    CustomerContactLog,
    CustomerFollowup,
    CustomerProfile,
    CustomerStatus,
    CustomerTag,
    CustomerTagLink,
    SupportViewAuditLog,
    SupportViewRequest,
    SystemAlert,
    UserFeedback,
)


class OperationsConflict(ValueError):
    pass


class OperationsUnavailable(RuntimeError):
    pass


def enforce_rate_limit(*, request, scope: str, limit: int, window_seconds: int = 3600) -> None:
    user_key = str(request.user.pk) if request.user.is_authenticated else "anonymous"
    digest = hashlib.sha256(f"{scope}:{user_key}".encode()).hexdigest()
    key = f"operations-rate:{digest}"
    try:
        if cache.add(key, 1, timeout=window_seconds):
            count = 1
        else:
            count = cache.incr(key)
    except Exception as exc:
        raise OperationsUnavailable("RATE_LIMIT_STORE_UNAVAILABLE") from exc
    if count > limit:
        raise Throttled(wait=window_seconds)


def _active_subscription(customer: User):
    return (
        Subscription.objects.filter(user=customer, status=Subscription.Status.ACTIVE)
        .select_related("plan")
        .first()
    )


def customer_payload(customer: User) -> dict:
    profile = CustomerProfile.objects.filter(customer=customer).select_related("status").first()
    assignment = (
        CustomerAssignment.objects.filter(customer=customer)
        .select_related("owner_admin__user")
        .first()
    )
    subscription = _active_subscription(customer)
    tags = CustomerTag.objects.filter(
        state=CustomerTag.State.ACTIVE, customer_links__customer=customer
    ).order_by("name")
    return {
        "id": str(customer.pk),
        "phone": customer.phone,
        "nickname": customer.nickname,
        "approval_status": customer.approval_status,
        "account_status": customer.account_status,
        "registered_at": customer.created_at,
        "profile": {
            "status": (
                {
                    "id": str(profile.status_id),
                    "key": profile.status.key,
                    "name": profile.status.name,
                }
                if profile and profile.status is not None
                else None
            ),
            "source": profile.source if profile else "",
            "internal_note": profile.internal_note if profile else "",
            "version": profile.version if profile else 1,
        },
        "tags": [{"id": str(tag.pk), "key": tag.key, "name": tag.name} for tag in tags],
        "owner": (
            {
                "id": str(assignment.owner_admin_id),
                "nickname": assignment.owner_admin.user.nickname,
            }
            if assignment and assignment.owner_admin is not None
            else None
        ),
        "subscription": (
            {
                "id": str(subscription.pk),
                "plan_key": subscription.plan.code,
                "is_trial": subscription.is_trial,
                "ends_at": subscription.ends_at,
            }
            if subscription
            else None
        ),
        "subject_count": Subject.objects.filter(user=customer).count(),
        "open_followup_count": CustomerFollowup.objects.filter(
            customer=customer, status=CustomerFollowup.Status.OPEN
        ).count(),
    }


@transaction.atomic
def update_customer_profile(*, request, customer_id, values: dict) -> CustomerProfile:
    customer = scoped_customer_or_404(request.user, request.admin_context, customer_id)
    profile, _ = CustomerProfile.objects.select_for_update().get_or_create(customer=customer)
    if profile.version != values["expected_version"]:
        raise OperationsConflict("CUSTOMER_PROFILE_VERSION_CONFLICT")
    before_status = profile.status.key if profile.status is not None else ""
    status_id = values.get("status_id", profile.status_id)
    status = None
    if status_id is not None:
        try:
            status = CustomerStatus.objects.get(pk=status_id, state=CustomerStatus.State.ACTIVE)
        except CustomerStatus.DoesNotExist as exc:
            raise OperationsConflict("CUSTOMER_STATUS_UNAVAILABLE") from exc
    if "status_id" in values:
        profile.status = status
    if "source" in values:
        profile.source = values["source"]
    if "internal_note" in values:
        profile.internal_note = values["internal_note"]
    profile.version += 1
    profile.save()

    if "tag_ids" in values:
        tags = list(
            CustomerTag.objects.filter(pk__in=values["tag_ids"], state=CustomerTag.State.ACTIVE)
        )
        if len(tags) != len(values["tag_ids"]):
            raise OperationsConflict("CUSTOMER_TAG_UNAVAILABLE")
        CustomerTagLink.objects.filter(customer=customer).exclude(tag__in=tags).delete()
        for tag in tags:
            CustomerTagLink.objects.get_or_create(
                customer=customer, tag=tag, defaults={"created_by": request.user}
            )

    record_audit_event(
        request=request,
        category="operations",
        action_key="customer.profile.update",
        outcome="succeeded",
        actor=request.user,
        subject=customer,
        target_type="customer_profile",
        target_id=profile.pk,
        safe_before={"status_key": before_status, "version": profile.version - 1},
        safe_after={
            "status_key": profile.status.key if profile.status is not None else "",
            "version": profile.version,
            "tag_count": CustomerTagLink.objects.filter(customer=customer).count(),
        },
    )
    return profile


@transaction.atomic
def create_contact(*, request, customer_id, values: dict) -> CustomerContactLog:
    customer = scoped_customer_or_404(request.user, request.admin_context, customer_id)
    contact = CustomerContactLog.objects.create(
        customer=customer,
        actor=request.admin_context.profile,
        contacted_at=values["contacted_at"],
        method=values["method"],
        content=values["content"],
        next_followup_at=values.get("next_followup_at"),
    )
    if contact.next_followup_at:
        CustomerFollowup.objects.create(
            customer=customer,
            assignee=request.admin_context.profile,
            source_contact=contact,
            due_at=contact.next_followup_at,
            note=values.get("followup_note") or "联系记录后续跟进",
        )
    record_audit_event(
        request=request,
        category="operations",
        action_key="customer.contact.create",
        outcome="succeeded",
        actor=request.user,
        subject=customer,
        target_type="customer_contact_log",
        target_id=contact.pk,
        safe_after={
            "method": contact.method,
            "followup_created": contact.next_followup_at is not None,
        },
    )
    return contact


@transaction.atomic
def create_followup(*, request, customer_id, values: dict) -> CustomerFollowup:
    customer = scoped_customer_or_404(request.user, request.admin_context, customer_id)
    row = CustomerFollowup.objects.create(
        customer=customer,
        assignee=request.admin_context.profile,
        due_at=values["due_at"],
        note=values["note"],
    )
    record_audit_event(
        request=request,
        category="operations",
        action_key="customer.followup.create",
        outcome="succeeded",
        actor=request.user,
        subject=customer,
        target_type="customer_followup",
        target_id=row.pk,
        safe_after={"status": row.status, "version": row.version},
    )
    return row


@transaction.atomic
def act_on_followup(*, request, followup_id, values: dict) -> CustomerFollowup:
    allowed = scoped_customers(request.user, request.admin_context)
    try:
        row = (
            CustomerFollowup.objects.select_for_update()
            .select_related("customer")
            .get(pk=followup_id, customer__in=allowed)
        )
    except CustomerFollowup.DoesNotExist as exc:
        raise OperationsConflict("FOLLOWUP_NOT_FOUND") from exc
    if row.version != values["expected_version"] or row.status != CustomerFollowup.Status.OPEN:
        raise OperationsConflict("FOLLOWUP_VERSION_CONFLICT")
    before = row.status
    action = values["action"]
    if action == "complete":
        row.status = CustomerFollowup.Status.COMPLETED
        row.completed_at = timezone.now()
    elif action == "cancel":
        row.status = CustomerFollowup.Status.CANCELLED
    else:
        row.due_at = values["due_at"]
        if "note" in values:
            row.note = values["note"]
    row.version += 1
    row.save()
    record_audit_event(
        request=request,
        category="operations",
        action_key=f"customer.followup.{action}",
        outcome="succeeded",
        actor=request.user,
        subject=row.customer,
        target_type="customer_followup",
        target_id=row.pk,
        safe_before={"status": before, "version": row.version - 1},
        safe_after={"status": row.status, "version": row.version},
    )
    return row


def contact_payload(row: CustomerContactLog) -> dict:
    return {
        "id": str(row.pk),
        "customer_id": str(row.customer_id),
        "actor_id": str(row.actor_id),
        "contacted_at": row.contacted_at,
        "method": row.method,
        "content": row.content,
        "next_followup_at": row.next_followup_at,
        "created_at": row.created_at,
    }


def followup_payload(row: CustomerFollowup) -> dict:
    return {
        "id": str(row.pk),
        "customer_id": str(row.customer_id),
        "assignee_id": str(row.assignee_id),
        "due_at": row.due_at,
        "note": row.note,
        "status": row.status,
        "completed_at": row.completed_at,
        "version": row.version,
        "created_at": row.created_at,
    }


def visible_announcements(user: User) -> list[Announcement]:
    now = timezone.now()
    rows = Announcement.objects.filter(status=Announcement.Status.PUBLISHED).filter(
        Q(starts_at__isnull=True) | Q(starts_at__lte=now),
        Q(ends_at__isnull=True) | Q(ends_at__gt=now),
    )
    subscription = _active_subscription(user)
    plan_key = subscription.plan.code if subscription else ""
    visible = []
    for row in rows:
        if row.audience == Announcement.Audience.ALL:
            visible.append(row)
        elif row.audience == Announcement.Audience.USER and str(user.pk) in row.audience_keys:
            visible.append(row)
        elif row.audience == Announcement.Audience.PLAN and plan_key in row.audience_keys:
            visible.append(row)
    return visible


def announcement_payload(row: Announcement, *, admin: bool = False) -> dict:
    payload = {
        "id": str(row.pk),
        "title": row.title,
        "body": row.body,
        "pinned": row.pinned,
        "starts_at": row.starts_at,
        "ends_at": row.ends_at,
        "published_at": row.published_at,
    }
    if admin:
        payload.update(
            {
                "audience": row.audience,
                "audience_keys": row.audience_keys,
                "status": row.status,
                "version": row.version,
                "created_at": row.created_at,
            }
        )
    return payload


def feedback_payload(row: UserFeedback, *, admin: bool = False) -> dict:
    payload = {
        "id": str(row.pk),
        "subject_id": str(row.subject_id) if row.subject_id else None,
        "module": row.module,
        "description": row.description,
        "status": row.status,
        "admin_reply": row.admin_reply,
        "replied_at": row.replied_at,
        "version": row.version,
        "created_at": row.created_at,
    }
    if admin:
        payload["user_id"] = str(row.user_id)
    return payload


def _append_tasks(result: list[dict], rows: Iterable, task_type: str, user_getter) -> None:
    for row in rows:
        user_id = user_getter(row)
        result.append(
            {
                "id": str(row.pk),
                "type": task_type,
                "status": row.status,
                "user_id": str(user_id),
                "created_at": row.created_at,
                "safe_error_code": getattr(row, "safe_error_code", ""),
            }
        )


def task_rows_for_users(user_ids, *, limit: int = 200) -> list[dict]:
    ids = list(user_ids)
    result: list[dict] = []
    _append_tasks(
        result,
        GeoDetectionJob.objects.filter(user_id__in=ids).order_by("-created_at")[:limit],
        "geo_detection",
        lambda row: row.user_id,
    )
    _append_tasks(
        result,
        StrategyReport.objects.filter(user_id__in=ids).order_by("-created_at")[:limit],
        "strategy",
        lambda row: row.user_id,
    )
    _append_tasks(
        result,
        ArticleGenerationJob.objects.filter(article__user_id__in=ids)
        .select_related("article")
        .order_by("-created_at")[:limit],
        "article_generation",
        lambda row: row.article.user_id,
    )
    _append_tasks(
        result,
        ImageGenerationJob.objects.filter(user_id__in=ids).order_by("-created_at")[:limit],
        "image_generation",
        lambda row: row.user_id,
    )
    result.sort(key=lambda item: item["created_at"], reverse=True)
    return result[:limit]


def usage_summary(customer: User) -> dict:
    return {
        "user_id": str(customer.pk),
        "subjects": Subject.objects.filter(user=customer).count(),
        "geo_detections": GeoDetectionJob.objects.filter(user=customer).count(),
        "strategies": StrategyReport.objects.filter(user=customer).count(),
        "articles": Article.objects.filter(user=customer).count(),
        "article_jobs": ArticleGenerationJob.objects.filter(article__user=customer).count(),
        "images": ImageAsset.objects.filter(user=customer).count(),
        "image_jobs": ImageGenerationJob.objects.filter(user=customer).count(),
    }


@transaction.atomic
def decide_article_moderation(*, request, article_id, values: dict) -> Article:
    customer_ids = scoped_customers(request.user, request.admin_context).values("pk")
    try:
        article = Article.objects.select_for_update().get(pk=article_id, user_id__in=customer_ids)
    except Article.DoesNotExist as exc:
        raise OperationsConflict("MODERATION_ITEM_NOT_FOUND") from exc
    if article.version != values["expected_version"]:
        raise OperationsConflict("MODERATION_VERSION_CONFLICT")
    decision = values["decision"]
    article.moderation_status = (
        Article.Moderation.PASSED if decision == "approve" else Article.Moderation.REJECTED
    )
    article.status = Article.Status.READY if decision == "approve" else Article.Status.REJECTED
    article.version += 1
    article.save()
    ArticleModerationReview.objects.create(
        article=article,
        kind=ArticleModerationReview.Kind.MANUAL,
        result=article.moderation_status,
        responsibility=values["responsibility"],
        safe_reason_code=values["reason_code"],
        review_no=article.moderation_reviews.count() + 1,
    )
    if values["responsibility"] == "system":
        record_compensation_alert("article", article.pk)
    record_audit_event(
        request=request,
        category="moderation",
        action_key=f"article.moderation.{decision}",
        outcome="succeeded",
        actor=request.user,
        subject=article.user,
        target_type="article",
        target_id=article.pk,
        safe_after={
            "decision": decision,
            "responsibility": values["responsibility"],
            "reason_code": values["reason_code"],
            "version": article.version,
        },
    )
    return article


@transaction.atomic
def decide_image_moderation(*, request, image_id, values: dict) -> ImageAsset:
    customer_ids = scoped_customers(request.user, request.admin_context).values("pk")
    try:
        image = ImageAsset.objects.select_for_update().get(pk=image_id, user_id__in=customer_ids)
    except ImageAsset.DoesNotExist as exc:
        raise OperationsConflict("MODERATION_ITEM_NOT_FOUND") from exc
    if image.version != values["expected_version"]:
        raise OperationsConflict("MODERATION_VERSION_CONFLICT")
    decision = values["decision"]
    image.moderation_status = (
        ImageAsset.ModerationStatus.APPROVED
        if decision == "approve"
        else ImageAsset.ModerationStatus.REJECTED
    )
    image.version += 1
    image.save()
    generation_job = image.generation_job if image.generation_job_id else None
    if generation_job is not None:
        ImageModerationReview.objects.create(
            job=generation_job,
            image=image,
            source=ImageModerationReview.Source.MANUAL,
            decision=image.moderation_status,
            risk_categories=[values["reason_code"]],
            responsibility=values["responsibility"],
            quota_released=False,
            actor=request.user,
            note=values.get("note", ""),
        )
    if values["responsibility"] == "system":
        record_compensation_alert("image", image.pk)
    record_audit_event(
        request=request,
        category="moderation",
        action_key=f"image.moderation.{decision}",
        outcome="succeeded",
        actor=request.user,
        subject=image.user,
        target_type="image",
        target_id=image.pk,
        safe_after={
            "decision": decision,
            "responsibility": values["responsibility"],
            "reason_code": values["reason_code"],
            "version": image.version,
        },
    )
    return image


def record_compensation_alert(kind: str, target_id) -> None:
    now = timezone.now()
    fingerprint = hashlib.sha256(f"moderation:{kind}:{target_id}".encode()).hexdigest()
    row, created = SystemAlert.objects.get_or_create(
        fingerprint=fingerprint,
        defaults={
            "category": "moderation_compensation_required",
            "severity": SystemAlert.Severity.IMPORTANT,
            "status": SystemAlert.Status.OPEN,
            "safe_summary": {"target_type": kind, "target_id": str(target_id)},
            "first_seen_at": now,
            "last_seen_at": now,
        },
    )
    if not created:
        SystemAlert.objects.filter(pk=row.pk).update(
            occurrences=F("occurrences") + 1,
            last_seen_at=now,
            status=SystemAlert.Status.OPEN,
            version=F("version") + 1,
        )


@transaction.atomic
def create_support_view(*, request, customer_id, reason: str, forced: bool) -> SupportViewRequest:
    customer = scoped_customer_or_404(request.user, request.admin_context, customer_id)
    if forced and not request.user.is_superuser:
        raise OperationsConflict("SUPPORT_VIEW_FORCE_FORBIDDEN")
    now = timezone.now()
    row = SupportViewRequest.objects.create(
        requester=request.admin_context.profile,
        customer=customer,
        reason=reason,
        forced=forced,
        status=SupportViewRequest.Status.ACTIVE if forced else SupportViewRequest.Status.PENDING,
        authorized_at=now if forced else None,
        expires_at=now + timedelta(minutes=30),
    )
    record_audit_event(
        request=request,
        category="support_view",
        action_key="support_view.force" if forced else "support_view.request",
        outcome="succeeded",
        actor=request.user,
        subject=customer,
        target_type="support_view_request",
        target_id=row.pk,
        safe_after={"forced": forced, "status": row.status, "version": row.version},
    )
    return row


def support_view_summary(*, request, support_id) -> dict:
    now = timezone.now()
    try:
        row = SupportViewRequest.objects.select_related("customer", "requester").get(
            pk=support_id, requester=request.admin_context.profile
        )
    except SupportViewRequest.DoesNotExist as exc:
        raise OperationsConflict("SUPPORT_VIEW_NOT_FOUND") from exc
    if row.status != SupportViewRequest.Status.ACTIVE or row.expires_at <= now:
        if row.status == SupportViewRequest.Status.ACTIVE and row.expires_at <= now:
            updated = SupportViewRequest.objects.filter(pk=row.pk, version=row.version).update(
                status=SupportViewRequest.Status.EXPIRED, version=row.version + 1
            )
            if updated:
                record_audit_event(
                    request=request,
                    category="support_view",
                    action_key="support_view.expire",
                    outcome="succeeded",
                    actor=request.user,
                    subject=row.customer,
                    target_type="support_view_request",
                    target_id=row.pk,
                    safe_after={"status": SupportViewRequest.Status.EXPIRED},
                )
        raise OperationsConflict("SUPPORT_VIEW_NOT_ACTIVE")
    SupportViewAuditLog.objects.create(
        support_request=row,
        actor=request.user,
        page_key="summary",
        outcome="viewed",
        request_id=request.request_id,
    )
    summary = usage_summary(row.customer)
    summary.update(
        {
            "nickname": row.customer.nickname,
            "approval_status": row.customer.approval_status,
            "account_status": row.customer.account_status,
            "read_only": True,
            "expires_at": row.expires_at,
        }
    )
    return summary
