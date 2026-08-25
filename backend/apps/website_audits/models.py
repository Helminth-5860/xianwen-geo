import uuid

from django.conf import settings
from django.db import models


class WebsiteAudit(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        QUEUED = "queued", "排队中"
        RUNNING = "running", "扫描中"
        SUCCEEDED = "succeeded", "已完成"
        FAILED = "failed", "失败"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="website_audits",
    )
    subject = models.ForeignKey(
        "subjects.Subject",
        on_delete=models.PROTECT,
        related_name="website_audits",
    )
    root_url = models.TextField()
    root_host = models.CharField(max_length=255, db_index=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    max_pages = models.PositiveIntegerField(default=200)
    discovered_count = models.PositiveIntegerField(default=0)
    selected_count = models.PositiveIntegerField(default=0)
    fetched_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    internal_link_count = models.PositiveIntegerField(default=0)
    external_link_count = models.PositiveIntegerField(default=0)
    robots_url = models.TextField(blank=True)
    robots_status = models.PositiveSmallIntegerField(null=True, blank=True)
    robots_text = models.TextField(blank=True)
    sitemap_urls = models.JSONField(default=list)
    stable_error_code = models.CharField(max_length=64, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "website_audits"
        ordering = ("-created_at", "id")
        indexes = [
            models.Index(fields=("user", "subject", "created_at"), name="website_audit_owner_idx"),
            models.Index(fields=("status", "created_at"), name="website_audit_status_idx"),
        ]


class WebsiteAuditPage(models.Model):  # noqa: DJ008
    class Source(models.TextChoices):
        ROOT = "root", "首页"
        SITEMAP = "sitemap", "Sitemap"
        INTERNAL_LINK = "internal_link", "站内链接"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    audit = models.ForeignKey(WebsiteAudit, on_delete=models.CASCADE, related_name="pages")
    url = models.TextField()
    final_url = models.TextField(blank=True)
    source = models.CharField(max_length=24, choices=Source.choices)
    depth = models.PositiveSmallIntegerField(default=0)
    http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    content_type = models.CharField(max_length=128, blank=True)
    response_ms = models.PositiveIntegerField(null=True, blank=True)
    response_bytes = models.PositiveIntegerField(default=0)
    redirect_count = models.PositiveSmallIntegerField(default=0)
    title = models.CharField(max_length=500, blank=True)
    meta_description = models.TextField(blank=True)
    canonical_url = models.TextField(blank=True)
    robots_meta = models.CharField(max_length=500, blank=True)
    html_lang = models.CharField(max_length=64, blank=True)
    viewport = models.CharField(max_length=500, blank=True)
    headings = models.JSONField(default=dict)
    open_graph = models.JSONField(default=dict)
    twitter_card = models.JSONField(default=dict)
    schema_types = models.JSONField(default=list)
    image_count = models.PositiveIntegerField(default=0)
    image_alt_missing_count = models.PositiveIntegerField(default=0)
    internal_links_count = models.PositiveIntegerField(default=0)
    external_links_count = models.PositiveIntegerField(default=0)
    text_characters = models.PositiveIntegerField(default=0)
    text_sample = models.TextField(blank=True)
    response_sha256 = models.CharField(max_length=64, blank=True)
    fetch_error = models.CharField(max_length=64, blank=True)
    fetched_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "website_audit_pages"
        ordering = ("depth", "url", "id")
        constraints = [
            models.UniqueConstraint(fields=("audit", "url"), name="website_audit_page_unique")
        ]
        indexes = [
            models.Index(fields=("audit", "http_status"), name="website_page_status_idx"),
            models.Index(fields=("audit", "source", "depth"), name="website_page_source_idx"),
        ]


class WebsiteAuditLink(models.Model):  # noqa: DJ008
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    audit = models.ForeignKey(WebsiteAudit, on_delete=models.CASCADE, related_name="links")
    source_page = models.ForeignKey(
        WebsiteAuditPage,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="outgoing_links",
    )
    destination_url = models.TextField()
    is_internal = models.BooleanField(db_index=True)
    anchor_text = models.CharField(max_length=500, blank=True)
    rel = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "website_audit_links"
        indexes = [
            models.Index(fields=("audit", "is_internal"), name="website_link_scope_idx"),
            models.Index(fields=("audit", "source_page"), name="website_link_source_idx"),
        ]


class WebsiteAuditFinding(models.Model):  # noqa: DJ008
    class Category(models.TextChoices):
        SEO = "seo", "SEO"
        GEO = "geo", "GEO"
        TECHNICAL = "technical", "技术"

    class Severity(models.TextChoices):
        CRITICAL = "critical", "严重"
        HIGH = "high", "高"
        MEDIUM = "medium", "中"
        LOW = "low", "低"
        INFO = "info", "建议"

    class Result(models.TextChoices):
        PASS = "pass", "通过"
        WARN = "warn", "警告"
        FAIL = "fail", "失败"
        INFO = "info", "信息"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    audit = models.ForeignKey(WebsiteAudit, on_delete=models.CASCADE, related_name="findings")
    page = models.ForeignKey(
        WebsiteAuditPage,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="findings",
    )
    category = models.CharField(max_length=16, choices=Category.choices)
    check_key = models.CharField(max_length=128)
    severity = models.CharField(max_length=16, choices=Severity.choices)
    result = models.CharField(max_length=16, choices=Result.choices)
    title = models.CharField(max_length=300)
    summary = models.TextField(blank=True)
    evidence = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "website_audit_findings"
        indexes = [
            models.Index(fields=("audit", "category", "severity"), name="website_finding_idx"),
            models.Index(fields=("audit", "check_key"), name="website_check_key_idx"),
        ]
