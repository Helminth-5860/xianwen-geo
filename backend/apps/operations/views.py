from __future__ import annotations

import csv
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import Http404, HttpResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_201_CREATED,
    HTTP_202_ACCEPTED,
    HTTP_409_CONFLICT,
    HTTP_503_SERVICE_UNAVAILABLE,
)
from rest_framework.views import APIView

from apps.admin_rbac.audit_services import record_audit_event
from apps.admin_rbac.permissions import HasAdminPermission
from apps.admin_rbac.scopes import scoped_customer_or_404, scoped_customers
from apps.articles.models import Article
from apps.core.error_codes import ErrorCode
from apps.core.responses import error_response
from apps.images.models import ImageAsset
from apps.subjects.models import Subject
from apps.subjects.permissions import IsAvailableAuthenticatedUser
from apps.users.phone_numbers import mask_phone

from .models import (
    Announcement,
    BackupRecord,
    CustomerContactLog,
    CustomerFollowup,
    CustomerStatus,
    CustomerTag,
    RetentionJob,
    SupportViewRequest,
    SystemAlert,
    UserFeedback,
)
from .readiness import release_readiness_report
from .serializers import (
    AnnouncementActionSerializer,
    AnnouncementWriteSerializer,
    BoundedPageSerializer,
    ContactCreateSerializer,
    CustomerCatalogUpdateSerializer,
    CustomerExportSerializer,
    CustomerProfileUpdateSerializer,
    FeedbackCreateSerializer,
    FeedbackReplySerializer,
    FollowupActionSerializer,
    FollowupCreateSerializer,
    ModerationDecisionSerializer,
    SupportViewCreateSerializer,
    SupportViewDecisionSerializer,
    SystemAlertActionSerializer,
)
from .services import (
    OperationsConflict,
    OperationsUnavailable,
    act_on_followup,
    announcement_payload,
    contact_payload,
    create_contact,
    create_followup,
    create_support_view,
    customer_payload,
    decide_article_moderation,
    decide_image_moderation,
    enforce_rate_limit,
    feedback_payload,
    followup_payload,
    support_view_summary,
    task_rows_for_users,
    update_customer_profile,
    usage_summary,
    visible_announcements,
)


def _no_store(response):
    response["Cache-Control"] = "no-store"
    return response


def _conflict(request, code: str, *, status: int = HTTP_409_CONFLICT):
    return _no_store(
        error_response(
            ErrorCode.VALIDATION_ERROR,
            status_code=status,
            request=request,
            message=code,
            details={"operations_code": code},
        )
    )


def _page(request, rows, payload):
    serializer = BoundedPageSerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    page = serializer.validated_data["page"]
    size = serializer.validated_data["page_size"]
    total = rows.count()
    start = (page - 1) * size
    items = [payload(row) for row in rows[start : start + size]]
    return {
        "items": items,
        "pagination": {
            "page": page,
            "page_size": size,
            "total": total,
            "total_pages": (total + size - 1) // size,
        },
    }


class AdminCustomerListView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "operations.customers.view"

    def get(self, request):
        rows = scoped_customers(request.user, request.admin_context).order_by("-created_at")
        query = request.query_params.get("q", "").strip()
        if query:
            rows = rows.filter(Q(phone__icontains=query) | Q(nickname__icontains=query))
        account_status = request.query_params.get("account_status", "")
        if account_status:
            rows = rows.filter(account_status=account_status)
        return _no_store(Response(_page(request, rows, customer_payload)))


def _csv_safe(value: object) -> str:
    text = str(value or "")
    return f"'{text}" if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


class AdminCustomerExportView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "operations.exports"

    @method_decorator(csrf_protect)
    def post(self, request):
        serializer = CustomerExportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rows = (
            scoped_customers(request.user, request.admin_context)
            .select_related("customer_profile__status")
            .annotate(
                subject_total=Count("subjects", distinct=True),
                open_followup_total=Count(
                    "customer_followups",
                    filter=Q(customer_followups__status=CustomerFollowup.Status.OPEN),
                    distinct=True,
                ),
            )
            .order_by("created_at", "pk")
        )
        row_count = rows.count()
        if row_count > 10_000:
            return _conflict(request, "EXPORT_ROW_LIMIT_EXCEEDED")

        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="customers.csv"'
        response["Cache-Control"] = "no-store"
        response.write("\ufeff")
        writer = csv.writer(response, lineterminator="\r\n")
        writer.writerow(
            (
                "customer_id",
                "phone_masked",
                "nickname",
                "approval_status",
                "account_status",
                "customer_status",
                "subject_count",
                "open_followup_count",
            )
        )
        for customer in rows:
            profile = getattr(customer, "customer_profile", None)
            status_key = profile.status.key if profile and profile.status is not None else ""
            writer.writerow(
                (
                    customer.pk,
                    mask_phone(customer.phone),
                    _csv_safe(customer.nickname),
                    customer.approval_status,
                    customer.account_status,
                    status_key,
                    customer.subject_total,
                    customer.open_followup_total,
                )
            )
        record_audit_event(
            request=request,
            category="operations",
            action_key="customer.export.csv",
            outcome="succeeded",
            actor=request.user,
            target_type="operations_export",
            target_id=request.user.pk,
            safe_after={"format": "csv", "row_count": row_count, "scope_enforced": True},
        )
        return response


class AdminCustomerDetailView(APIView):
    permission_classes = [HasAdminPermission]
    required_permissions_by_method = {
        "GET": "operations.customers.view",
        "PATCH": "operations.customers.manage",
    }

    def get(self, request, customer_id):
        customer = scoped_customer_or_404(request.user, request.admin_context, customer_id)
        return _no_store(Response(customer_payload(customer)))

    @method_decorator(csrf_protect)
    def patch(self, request, customer_id):
        serializer = CustomerProfileUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            update_customer_profile(
                request=request, customer_id=customer_id, values=serializer.validated_data
            )
        except OperationsConflict as exc:
            return _conflict(request, str(exc))
        customer = scoped_customer_or_404(request.user, request.admin_context, customer_id)
        return _no_store(Response(customer_payload(customer)))


class AdminCustomerContactListCreateView(APIView):
    permission_classes = [HasAdminPermission]
    required_permissions_by_method = {
        "GET": "operations.customers.view",
        "POST": "operations.customers.manage",
    }

    def get(self, request, customer_id):
        customer = scoped_customer_or_404(request.user, request.admin_context, customer_id)
        rows = CustomerContactLog.objects.filter(customer=customer)
        return _no_store(Response(_page(request, rows, contact_payload)))

    @method_decorator(csrf_protect)
    def post(self, request, customer_id):
        serializer = ContactCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = create_contact(
            request=request, customer_id=customer_id, values=serializer.validated_data
        )
        return _no_store(Response(contact_payload(row), status=HTTP_201_CREATED))


class AdminCustomerFollowupListCreateView(APIView):
    permission_classes = [HasAdminPermission]
    required_permissions_by_method = {
        "GET": "operations.customers.view",
        "POST": "operations.customers.manage",
    }

    def get(self, request, customer_id):
        customer = scoped_customer_or_404(request.user, request.admin_context, customer_id)
        rows = CustomerFollowup.objects.filter(customer=customer)
        return _no_store(Response(_page(request, rows, followup_payload)))

    @method_decorator(csrf_protect)
    def post(self, request, customer_id):
        serializer = FollowupCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = create_followup(
            request=request, customer_id=customer_id, values=serializer.validated_data
        )
        return _no_store(Response(followup_payload(row), status=HTTP_201_CREATED))


class AdminFollowupActionView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "operations.customers.manage"

    @method_decorator(csrf_protect)
    def post(self, request, followup_id):
        serializer = FollowupActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            row = act_on_followup(
                request=request, followup_id=followup_id, values=serializer.validated_data
            )
        except OperationsConflict as exc:
            return _conflict(request, str(exc))
        return _no_store(Response(followup_payload(row)))


class _AdminCatalogView(APIView):
    permission_classes = [HasAdminPermission]
    required_permissions_by_method = {
        "GET": "operations.customers.view",
        "POST": "operations.customers.manage",
    }
    model: Any = CustomerStatus

    def get(self, request):
        rows = self.model.objects.all()
        return _no_store(
            Response(
                [
                    {
                        "id": str(row.pk),
                        "key": row.key,
                        "name": row.name,
                        "state": row.state,
                        "version": row.version,
                    }
                    for row in rows
                ]
            )
        )

    @method_decorator(csrf_protect)
    def post(self, request):
        key = str(request.data.get("key", "")).strip().lower()
        name = str(request.data.get("name", "")).strip()
        if not key or len(key) > 64 or not name or len(name) > 100:
            return _conflict(request, "CUSTOMER_CATALOG_INVALID", status=422)
        try:
            with transaction.atomic():
                row = self.model.objects.create(key=key, name=name)
                record_audit_event(
                    request=request,
                    category="operations",
                    action_key="customer.catalog.create",
                    outcome="succeeded",
                    actor=request.user,
                    target_type=self.model._meta.db_table,
                    target_id=row.pk,
                    safe_after={"key": key, "version": row.version},
                )
        except IntegrityError:
            return _conflict(request, "CUSTOMER_CATALOG_KEY_CONFLICT")
        return _no_store(Response({"id": str(row.pk), "key": key, "name": name}, status=201))


class AdminCustomerStatusListCreateView(_AdminCatalogView):
    pass


class AdminCustomerTagListCreateView(_AdminCatalogView):
    model = CustomerTag


class _AdminCatalogDetailView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "operations.customers.manage"
    model: Any = CustomerStatus

    @method_decorator(csrf_protect)
    def patch(self, request, catalog_id):
        serializer = CustomerCatalogUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                row = self.model.objects.select_for_update().get(pk=catalog_id)
                if row.version != serializer.validated_data["expected_version"]:
                    raise OperationsConflict("CUSTOMER_CATALOG_VERSION_CONFLICT")
                before = {"state": row.state, "version": row.version}
                if "name" in serializer.validated_data:
                    row.name = serializer.validated_data["name"]
                if "state" in serializer.validated_data:
                    row.state = serializer.validated_data["state"]
                row.version += 1
                row.save()
                record_audit_event(
                    request=request,
                    category="operations",
                    action_key="customer.catalog.update",
                    outcome="succeeded",
                    actor=request.user,
                    target_type=self.model._meta.db_table,
                    target_id=row.pk,
                    safe_before=before,
                    safe_after={"state": row.state, "version": row.version},
                )
        except self.model.DoesNotExist as exc:
            raise Http404 from exc
        except OperationsConflict as exc:
            return _conflict(request, str(exc))
        return _no_store(
            Response(
                {
                    "id": str(row.pk),
                    "key": row.key,
                    "name": row.name,
                    "state": row.state,
                    "version": row.version,
                }
            )
        )


class AdminCustomerStatusDetailView(_AdminCatalogDetailView):
    pass


class AdminCustomerTagDetailView(_AdminCatalogDetailView):
    model = CustomerTag


class AnnouncementListView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request):
        return _no_store(
            Response([announcement_payload(row) for row in visible_announcements(request.user)])
        )


class AdminAnnouncementListCreateView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "operations.announcements.manage"

    def get(self, request):
        return _no_store(
            Response(
                _page(
                    request,
                    Announcement.objects.all(),
                    lambda row: announcement_payload(row, admin=True),
                )
            )
        )

    @method_decorator(csrf_protect)
    def post(self, request):
        serializer = AnnouncementWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        values.pop("expected_version", None)
        if "title" not in values or "body" not in values:
            return _conflict(request, "ANNOUNCEMENT_FIELDS_REQUIRED", status=422)
        with transaction.atomic():
            row = Announcement.objects.create(created_by=request.user, **values)
            record_audit_event(
                request=request,
                category="operations",
                action_key="announcement.create",
                outcome="succeeded",
                actor=request.user,
                target_type="announcement",
                target_id=row.pk,
                safe_after={"audience": row.audience, "target_count": len(row.audience_keys)},
            )
        return _no_store(Response(announcement_payload(row, admin=True), status=HTTP_201_CREATED))


class AdminAnnouncementActionView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "operations.announcements.manage"

    @method_decorator(csrf_protect)
    def post(self, request, announcement_id):
        serializer = AnnouncementActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        try:
            with transaction.atomic():
                row = Announcement.objects.select_for_update().get(pk=announcement_id)
                if row.version != values["expected_version"]:
                    raise OperationsConflict("ANNOUNCEMENT_VERSION_CONFLICT")
                action = values["action"]
                if action == "publish":
                    row.status = Announcement.Status.PUBLISHED
                    row.published_at = timezone.now()
                else:
                    row.status = Announcement.Status.DISABLED
                row.version += 1
                row.save()
                record_audit_event(
                    request=request,
                    category="operations",
                    action_key=f"announcement.{action}",
                    outcome="succeeded",
                    actor=request.user,
                    target_type="announcement",
                    target_id=row.pk,
                    safe_after={"status": row.status, "version": row.version},
                )
        except Announcement.DoesNotExist as exc:
            raise Http404 from exc
        except OperationsConflict as exc:
            return _conflict(request, str(exc))
        return _no_store(Response(announcement_payload(row, admin=True)))


class FeedbackListCreateView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request):
        rows = UserFeedback.objects.filter(user=request.user)
        return _no_store(Response(_page(request, rows, feedback_payload)))

    @method_decorator(csrf_protect)
    def post(self, request):
        try:
            enforce_rate_limit(request=request, scope="feedback-create", limit=20)
        except OperationsUnavailable:
            return _conflict(
                request, "RATE_LIMIT_STORE_UNAVAILABLE", status=HTTP_503_SERVICE_UNAVAILABLE
            )
        serializer = FeedbackCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        subject = None
        if values.get("subject_id"):
            try:
                subject = Subject.objects.get(pk=values["subject_id"], user=request.user)
            except Subject.DoesNotExist as exc:
                raise Http404 from exc
        row = UserFeedback.objects.create(
            user=request.user,
            subject=subject,
            module=values["module"],
            description=values["description"],
        )
        return _no_store(Response(feedback_payload(row), status=HTTP_201_CREATED))


class FeedbackDetailView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request, feedback_id):
        try:
            row = UserFeedback.objects.get(pk=feedback_id, user=request.user)
        except UserFeedback.DoesNotExist as exc:
            raise Http404 from exc
        return _no_store(Response(feedback_payload(row)))


class AdminFeedbackListView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "operations.feedback.manage"

    def get(self, request):
        customers = scoped_customers(request.user, request.admin_context)
        rows = UserFeedback.objects.filter(user__in=customers)
        status = request.query_params.get("status", "")
        if status:
            rows = rows.filter(status=status)
        return _no_store(
            Response(_page(request, rows, lambda row: feedback_payload(row, admin=True)))
        )


class AdminFeedbackActionView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "operations.feedback.manage"

    @method_decorator(csrf_protect)
    def post(self, request, feedback_id):
        serializer = FeedbackReplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        customers = scoped_customers(request.user, request.admin_context).values("pk")
        try:
            with transaction.atomic():
                row = UserFeedback.objects.select_for_update().get(
                    pk=feedback_id, user_id__in=customers
                )
                if row.version != values["expected_version"]:
                    raise OperationsConflict("FEEDBACK_VERSION_CONFLICT")
                if values["action"] == "reply":
                    row.admin_reply = values["reply"].strip()
                    row.replied_by = request.user
                    row.replied_at = timezone.now()
                    row.status = UserFeedback.Status.REPLIED
                else:
                    row.status = UserFeedback.Status.CLOSED
                row.version += 1
                row.save()
                record_audit_event(
                    request=request,
                    category="operations",
                    action_key=f"feedback.{values['action']}",
                    outcome="succeeded",
                    actor=request.user,
                    subject=row.user,
                    target_type="user_feedback",
                    target_id=row.pk,
                    safe_after={"status": row.status, "version": row.version},
                )
        except UserFeedback.DoesNotExist as exc:
            raise Http404 from exc
        except OperationsConflict as exc:
            return _conflict(request, str(exc))
        return _no_store(Response(feedback_payload(row, admin=True)))


class UsageRecordsView(APIView):
    permission_classes = [IsAvailableAuthenticatedUser]

    def get(self, request):
        return _no_store(
            Response(
                {
                    "summary": usage_summary(request.user),
                    "tasks": task_rows_for_users([request.user.pk], limit=100),
                }
            )
        )


class AdminTasksView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "operations.tasks.view"

    def get(self, request):
        users = scoped_customers(request.user, request.admin_context)
        user_id = request.query_params.get("user_id", "")
        if user_id:
            users = users.filter(pk=user_id)
        rows = task_rows_for_users(users.values_list("pk", flat=True), limit=500)
        task_type = request.query_params.get("type", "")
        status = request.query_params.get("status", "")
        if task_type:
            rows = [row for row in rows if row["type"] == task_type]
        if status:
            rows = [row for row in rows if row["status"] == status]
        return _no_store(Response({"items": rows[:200], "safe_projection": True}))


class AdminDashboardView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "operations.dashboard.view"

    def get(self, request):
        customers = scoped_customers(request.user, request.admin_context)
        ids = customers.values_list("pk", flat=True)
        tasks = task_rows_for_users(ids, limit=500)
        counts: dict[str, int] = {}
        for item in tasks:
            key = f"{item['type']}:{item['status']}"
            counts[key] = counts.get(key, 0) + 1
        payload = {
            "customers": {
                "total": customers.count(),
                "pending_review": customers.filter(approval_status="pending").count(),
                "active": customers.filter(account_status="active").count(),
            },
            "followups": {
                "open": CustomerFollowup.objects.filter(
                    customer__in=customers, status="open"
                ).count(),
                "overdue": CustomerFollowup.objects.filter(
                    customer__in=customers, status="open", due_at__lt=timezone.now()
                ).count(),
            },
            "feedback_open": UserFeedback.objects.filter(user__in=customers, status="open").count(),
            "moderation": {
                "articles": Article.objects.filter(
                    user__in=customers, moderation_status=Article.Moderation.MANUAL_REVIEW
                ).count(),
                "images": ImageAsset.objects.filter(
                    user__in=customers,
                    moderation_status=ImageAsset.ModerationStatus.SUSPECTED,
                ).count(),
            },
            "task_counts": counts,
            "generated_at": timezone.now(),
        }
        return _no_store(Response(payload))


class AdminModerationListView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "operations.moderation.view"

    def get(self, request):
        customers = scoped_customers(request.user, request.admin_context)
        articles = Article.objects.filter(
            user__in=customers, moderation_status=Article.Moderation.MANUAL_REVIEW
        ).order_by("created_at")[:100]
        images = ImageAsset.objects.filter(
            user__in=customers, moderation_status=ImageAsset.ModerationStatus.SUSPECTED
        ).order_by("created_at")[:100]
        return _no_store(
            Response(
                {
                    "articles": [
                        {
                            "id": str(row.pk),
                            "user_id": str(row.user_id),
                            "subject_id": str(row.subject_id),
                            "status": row.moderation_status,
                            "version": row.version,
                            "created_at": row.created_at,
                        }
                        for row in articles
                    ],
                    "images": [
                        {
                            "id": str(row.pk),
                            "user_id": str(row.user_id),
                            "subject_id": str(row.subject_id),
                            "status": row.moderation_status,
                            "version": row.version,
                            "created_at": row.created_at,
                        }
                        for row in images
                    ],
                }
            )
        )


class AdminArticleModerationDecisionView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "operations.moderation.manage"

    @method_decorator(csrf_protect)
    def post(self, request, article_id):
        serializer = ModerationDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            row = decide_article_moderation(
                request=request, article_id=article_id, values=serializer.validated_data
            )
        except OperationsConflict as exc:
            return _conflict(request, str(exc))
        return _no_store(
            Response({"id": str(row.pk), "status": row.moderation_status, "version": row.version})
        )


class AdminImageModerationDecisionView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "operations.moderation.manage"

    @method_decorator(csrf_protect)
    def post(self, request, image_id):
        serializer = ModerationDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            row = decide_image_moderation(
                request=request, image_id=image_id, values=serializer.validated_data
            )
        except OperationsConflict as exc:
            return _conflict(request, str(exc))
        return _no_store(
            Response({"id": str(row.pk), "status": row.moderation_status, "version": row.version})
        )


class AdminSupportViewCreateView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "operations.support_view"

    @method_decorator(csrf_protect)
    def post(self, request, customer_id):
        serializer = SupportViewCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            row = create_support_view(
                request=request, customer_id=customer_id, **serializer.validated_data
            )
        except OperationsConflict as exc:
            return _conflict(request, str(exc), status=403)
        return _no_store(
            Response(
                {
                    "id": str(row.pk),
                    "status": row.status,
                    "forced": row.forced,
                    "expires_at": row.expires_at,
                    "version": row.version,
                },
                status=HTTP_202_ACCEPTED,
            )
        )


class SupportViewDecisionView(APIView):
    permission_classes = [IsAuthenticated]

    @method_decorator(csrf_protect)
    def post(self, request, support_id):
        serializer = SupportViewDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        try:
            with transaction.atomic():
                row = SupportViewRequest.objects.select_for_update().get(
                    pk=support_id, customer=request.user
                )
                if row.version != values["expected_version"]:
                    raise OperationsConflict("SUPPORT_VIEW_VERSION_CONFLICT")
                decision = values["decision"]
                now = timezone.now()
                if decision in {"authorize", "reject"} and row.status != "pending":
                    raise OperationsConflict("SUPPORT_VIEW_STATE_CONFLICT")
                if decision == "authorize":
                    row.status = SupportViewRequest.Status.ACTIVE
                    row.authorized_at = now
                elif decision == "reject":
                    row.status = SupportViewRequest.Status.REJECTED
                elif row.status == SupportViewRequest.Status.ACTIVE:
                    row.status = SupportViewRequest.Status.REVOKED
                    row.revoked_at = now
                else:
                    raise OperationsConflict("SUPPORT_VIEW_STATE_CONFLICT")
                row.version += 1
                row.save()
                record_audit_event(
                    request=request,
                    category="support_view",
                    action_key=f"support_view.user.{decision}",
                    outcome="succeeded",
                    actor=request.user,
                    subject=request.user,
                    target_type="support_view_request",
                    target_id=row.pk,
                    safe_after={"status": row.status, "version": row.version},
                )
        except SupportViewRequest.DoesNotExist as exc:
            raise Http404 from exc
        except OperationsConflict as exc:
            return _conflict(request, str(exc))
        return _no_store(
            Response({"id": str(row.pk), "status": row.status, "version": row.version})
        )


class AdminSupportViewSummaryView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "operations.support_view"

    def get(self, request, support_id):
        try:
            payload = support_view_summary(request=request, support_id=support_id)
        except OperationsConflict as exc:
            return _conflict(request, str(exc), status=403)
        return _no_store(Response(payload))


class AdminReleaseReadinessView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "release.readiness.view"

    def get(self, request):
        return _no_store(Response(release_readiness_report()))


class AdminSystemAlertsView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "operations.alerts.view"

    def get(self, request):
        rows = SystemAlert.objects.all()
        return _no_store(
            Response(
                _page(
                    request,
                    rows,
                    lambda row: {
                        "id": str(row.pk),
                        "category": row.category,
                        "severity": row.severity,
                        "status": row.status,
                        "occurrences": row.occurrences,
                        "safe_summary": row.safe_summary,
                        "last_seen_at": row.last_seen_at,
                        "version": row.version,
                    },
                )
            )
        )


class AdminSystemAlertActionView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "operations.alerts.manage"

    @method_decorator(csrf_protect)
    def post(self, request, alert_id):
        serializer = SystemAlertActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                row = SystemAlert.objects.select_for_update().get(pk=alert_id)
                if row.version != serializer.validated_data["expected_version"]:
                    raise OperationsConflict("SYSTEM_ALERT_VERSION_CONFLICT")
                action = serializer.validated_data["action"]
                if action == "acknowledge" and row.status != SystemAlert.Status.OPEN:
                    raise OperationsConflict("SYSTEM_ALERT_STATE_CONFLICT")
                if action == "resolve" and row.status not in {
                    SystemAlert.Status.OPEN,
                    SystemAlert.Status.ACKNOWLEDGED,
                }:
                    raise OperationsConflict("SYSTEM_ALERT_STATE_CONFLICT")
                row.status = (
                    SystemAlert.Status.ACKNOWLEDGED
                    if action == "acknowledge"
                    else SystemAlert.Status.RESOLVED
                )
                row.handled_by = request.user
                row.version += 1
                row.save()
                record_audit_event(
                    request=request,
                    category="operations",
                    action_key=f"system_alert.{action}",
                    outcome="succeeded",
                    actor=request.user,
                    target_type="system_alert",
                    target_id=row.pk,
                    safe_after={"status": row.status, "version": row.version},
                )
        except SystemAlert.DoesNotExist as exc:
            raise Http404 from exc
        except OperationsConflict as exc:
            return _conflict(request, str(exc))
        return _no_store(
            Response({"id": str(row.pk), "status": row.status, "version": row.version})
        )


class AdminBackupRecordsView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "operations.backups.view"

    def get(self, request):
        rows = BackupRecord.objects.all()
        return _no_store(
            Response(
                _page(
                    request,
                    rows,
                    lambda row: {
                        "id": str(row.pk),
                        "kind": row.kind,
                        "scope": row.scope,
                        "encrypted": row.encrypted,
                        "status": row.status,
                        "checksum_present": bool(row.checksum_sha256),
                        "restore_verified_at": row.restore_verified_at,
                        "safe_error_code": row.safe_error_code,
                        "created_at": row.created_at,
                    },
                )
            )
        )


class AdminRetentionJobsView(APIView):
    permission_classes = [HasAdminPermission]
    required_permission = "operations.retention.view"

    def get(self, request):
        rows = RetentionJob.objects.all()
        return _no_store(
            Response(
                _page(
                    request,
                    rows,
                    lambda row: {
                        "id": str(row.pk),
                        "kind": row.kind,
                        "scope": row.scope,
                        "status": row.status,
                        "safe_summary": row.safe_summary,
                        "created_at": row.created_at,
                        "finished_at": row.finished_at,
                    },
                )
            )
        )
