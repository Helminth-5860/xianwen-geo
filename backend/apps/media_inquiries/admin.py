from django.contrib import admin
from django.db.models import F
from django.utils import timezone

from .models import PaidMediaInquiry


@admin.register(PaidMediaInquiry)
class PaidMediaInquiryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "subject",
        "item_count",
        "total_price",
        "status",
        "created_at",
    )
    list_filter = ("status", "created_at")
    search_fields = (
        "user__phone",
        "user__nickname",
        "subject__current_version__official_name",
    )
    ordering = ("-created_at",)
    readonly_fields = (
        "id",
        "user",
        "tenant",
        "subject",
        "selected_media",
        "item_count",
        "total_price",
        "status",
        "version",
        "idempotency_key_digest",
        "request_digest",
        "request_id",
        "created_at",
        "updated_at",
    )
    actions = ("mark_contacted", "mark_completed", "mark_cancelled")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="标记为已联系")
    def mark_contacted(self, request, queryset):
        queryset.filter(status=PaidMediaInquiry.Status.PENDING).update(
            status=PaidMediaInquiry.Status.CONTACTED,
            version=F("version") + 1,
            updated_at=timezone.now(),
        )

    @admin.action(description="标记为已完成")
    def mark_completed(self, request, queryset):
        queryset.filter(
            status__in=(PaidMediaInquiry.Status.PENDING, PaidMediaInquiry.Status.CONTACTED)
        ).update(
            status=PaidMediaInquiry.Status.COMPLETED,
            version=F("version") + 1,
            updated_at=timezone.now(),
        )

    @admin.action(description="标记为已取消")
    def mark_cancelled(self, request, queryset):
        queryset.filter(
            status__in=(PaidMediaInquiry.Status.PENDING, PaidMediaInquiry.Status.CONTACTED)
        ).update(
            status=PaidMediaInquiry.Status.CANCELLED,
            version=F("version") + 1,
            updated_at=timezone.now(),
        )
