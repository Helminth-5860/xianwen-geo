from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class PaidMediaInquiry(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        PENDING = "pending", "待处理"
        CONTACTED = "contacted", "已联系"
        CANCELLED = "cancelled", "已取消"
        COMPLETED = "completed", "已完成"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="paid_media_inquiries",
    )
    tenant = models.ForeignKey(
        "users.Tenant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="paid_media_inquiries",
    )
    subject = models.ForeignKey(
        "subjects.Subject",
        on_delete=models.PROTECT,
        related_name="paid_media_inquiries",
    )
    selected_media = models.JSONField()
    item_count = models.PositiveIntegerField()
    total_price = models.DecimalField(max_digits=16, decimal_places=2)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    version = models.PositiveBigIntegerField(default=1)
    idempotency_key_digest = models.CharField(max_length=64, unique=True)
    request_digest = models.CharField(max_length=64)
    request_id = models.UUIDField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "paid_media_inquiries"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(
                fields=("user", "subject", "created_at"),
                name="media_inquiry_owner_idx",
            ),
            models.Index(fields=("status", "created_at"), name="media_inquiry_status_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=("pending", "contacted", "cancelled", "completed")),
                name="media_inquiry_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(item_count__gte=1), name="media_inquiry_items_gte_1"
            ),
            models.CheckConstraint(
                condition=Q(total_price__gte=0), name="media_inquiry_total_nonnegative"
            ),
            models.CheckConstraint(condition=Q(version__gte=1), name="media_inquiry_version_gte_1"),
        ]

    def delete(self, *args, **kwargs):
        raise RuntimeError("媒体服务申请记录不能删除。")
