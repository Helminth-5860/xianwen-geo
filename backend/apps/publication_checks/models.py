from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class PublicationVerificationCheck(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        PUBLISHED = "published", "Published"
        FAILED = "failed", "Failed"
        UNKNOWN = "unknown", "Unknown"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    subject = models.ForeignKey(
        "subjects.Subject",
        on_delete=models.PROTECT,
        related_name="publication_verification_checks",
    )
    requested_url = models.TextField()
    final_url = models.TextField()
    hostname = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices)
    page_title = models.CharField(max_length=500, blank=True)
    http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    response_time_ms = models.PositiveIntegerField(null=True, blank=True)
    result_message = models.CharField(max_length=500, blank=True)
    safe_failure_code = models.CharField(max_length=100, blank=True)
    checked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "publication_verification_checks"
        ordering = ("-checked_at", "-id")
        indexes = [
            models.Index(
                fields=("user", "subject", "-checked_at"),
                name="pubverify_user_subj_idx",
            )
        ]
