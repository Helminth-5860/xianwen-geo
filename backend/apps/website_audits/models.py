import uuid

from django.conf import settings
from django.db import models


class WebsiteAudit(models.Model):  # noqa: DJ008
    class Status(models.TextChoices):
        QUEUED = "queued", "排队中"
        RUNNING = "running", "扫描中"
        SUCCEEDED = "succeeded", "已完成"
        FAILED = "failed", "失败"

    class BrowserStatus(models.TextChoices):
        NOT_STARTED = "not_started", "未开始"
        QUEUED = "queued", "排队中"
        RUNNING = "running", "浏览器检测中"
        SUCCEEDED = "succeeded", "已完成"
        PARTIAL = "partial", "部分完成"
        FAILED = "failed", "失败"
        DISABLED = "disabled", "未启用"

    class SemanticStatus(models.TextChoices):
        NOT_STARTED = "not_started", "未开始"
        QUEUED = "queued", "排队中"
        RUNNING = "running", "语义检测中"
        SUCCEEDED = "succeeded", "已完成"
        FAILED = "failed", "失败"
        DISABLED = "disabled", "未启用"

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

    browser_status = models.CharField(
        max_length=16,
        choices=BrowserStatus.choices,
        default=BrowserStatus.NOT_STARTED,
    )
    browser_profiles = models.JSONField(default=list)
    browser_selected_count = models.PositiveIntegerField(default=0)
    browser_completed_count = models.PositiveIntegerField(default=0)
    browser_failed_count = models.PositiveIntegerField(default=0)
    browser_error_code = models.CharField(max_length=64, blank=True)
    browser_started_at = models.DateTimeField(null=True, blank=True)
    browser_finished_at = models.DateTimeField(null=True, blank=True)

    semantic_status = models.CharField(
        max_length=16,
        choices=SemanticStatus.choices,
        default=SemanticStatus.NOT_STARTED,
    )
    semantic_provider_key = models.CharField(max_length=64, blank=True)
    semantic_model_id = models.CharField(max_length=255, blank=True)
    semantic_runtime_version = models.PositiveBigIntegerField(null=True, blank=True)
    semantic_prompt_version = models.CharField(max_length=64, blank=True)
    semantic_page_count = models.PositiveIntegerField(default=0)
    semantic_question_count = models.PositiveIntegerField(default=0)
    semantic_scores = models.JSONField(default=dict)
    semantic_result = models.JSONField(default=dict)
    semantic_input_tokens = models.PositiveIntegerField(default=0)
    semantic_output_tokens = models.PositiveIntegerField(default=0)
    semantic_total_tokens = models.PositiveIntegerField(default=0)
    semantic_latency_ms = models.PositiveIntegerField(null=True, blank=True)
    semantic_error_code = models.CharField(max_length=64, blank=True)
    semantic_started_at = models.DateTimeField(null=True, blank=True)
    semantic_finished_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "website_audits"
        ordering = ("-created_at", "id")
        indexes = [
            models.Index(fields=("user", "subject", "created_at"), name="website_audit_owner_idx"),
            models.Index(fields=("status", "created_at"), name="website_audit_status_idx"),
            models.Index(
                fields=("browser_status", "created_at"),
                name="website_browser_status_idx",
            ),
            models.Index(
                fields=("semantic_status", "created_at"),
                name="website_semantic_status_idx",
            ),
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
    schema_entities = models.JSONField(default=list)
    jsonld_block_count = models.PositiveIntegerField(default=0)
    jsonld_invalid_count = models.PositiveIntegerField(default=0)
    image_count = models.PositiveIntegerField(default=0)
    image_alt_missing_count = models.PositiveIntegerField(default=0)
    paragraph_count = models.PositiveIntegerField(default=0)
    list_count = models.PositiveIntegerField(default=0)
    table_count = models.PositiveIntegerField(default=0)
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


class WebsiteAuditBrowserSnapshot(models.Model):  # noqa: DJ008
    class Profile(models.TextChoices):
        MOBILE = "mobile", "移动端"
        DESKTOP = "desktop", "桌面端"

    class Status(models.TextChoices):
        SUCCEEDED = "succeeded", "成功"
        FAILED = "failed", "失败"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    audit = models.ForeignKey(
        WebsiteAudit,
        on_delete=models.CASCADE,
        related_name="browser_snapshots",
    )
    page = models.ForeignKey(
        WebsiteAuditPage,
        on_delete=models.CASCADE,
        related_name="browser_snapshots",
    )
    profile = models.CharField(max_length=16, choices=Profile.choices)
    status = models.CharField(max_length=16, choices=Status.choices)
    final_url = models.TextField(blank=True)
    navigation_ms = models.PositiveIntegerField(null=True, blank=True)
    ttfb_ms = models.PositiveIntegerField(null=True, blank=True)
    dom_content_loaded_ms = models.PositiveIntegerField(null=True, blank=True)
    load_ms = models.PositiveIntegerField(null=True, blank=True)
    fcp_ms = models.PositiveIntegerField(null=True, blank=True)
    lcp_ms = models.PositiveIntegerField(null=True, blank=True)
    cls = models.FloatField(null=True, blank=True)
    tbt_ms = models.PositiveIntegerField(null=True, blank=True)
    request_count = models.PositiveIntegerField(default=0)
    failed_request_count = models.PositiveIntegerField(default=0)
    blocked_request_count = models.PositiveIntegerField(default=0)
    transfer_bytes = models.PositiveBigIntegerField(default=0)
    cross_host_request_count = models.PositiveIntegerField(default=0)
    cross_host_transfer_bytes = models.PositiveBigIntegerField(default=0)
    resource_summary = models.JSONField(default=dict)
    console_error_count = models.PositiveIntegerField(default=0)
    page_error_count = models.PositiveIntegerField(default=0)
    dom_nodes = models.PositiveIntegerField(default=0)
    rendered_html_characters = models.PositiveIntegerField(default=0)
    rendered_text_characters = models.PositiveIntegerField(default=0)
    static_text_characters = models.PositiveIntegerField(default=0)
    text_delta = models.IntegerField(default=0)
    text_growth_ratio = models.FloatField(null=True, blank=True)
    rendered_title = models.CharField(max_length=500, blank=True)
    rendered_meta_description = models.TextField(blank=True)
    rendered_canonical_url = models.TextField(blank=True)
    rendered_schema_types = models.JSONField(default=list)
    rendered_heading_counts = models.JSONField(default=dict)
    visible_image_count = models.PositiveIntegerField(default=0)
    images_without_alt = models.PositiveIntegerField(default=0)
    failure_code = models.CharField(max_length=64, blank=True)
    evidence = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "website_audit_browser_snapshots"
        ordering = ("page_id", "profile", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("audit", "page", "profile"),
                name="website_browser_snapshot_unique",
            )
        ]
        indexes = [
            models.Index(
                fields=("audit", "profile", "status"),
                name="website_browser_profile_idx",
            ),
            models.Index(
                fields=("audit", "page"),
                name="website_browser_page_idx",
            ),
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

    class Method(models.TextChoices):
        DETERMINISTIC = "deterministic", "程序检测"
        BROWSER = "browser", "浏览器检测"
        SEMANTIC = "semantic", "语义分析"

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
    dimension = models.CharField(max_length=64, blank=True)
    check_key = models.CharField(max_length=128)
    rule_version = models.CharField(max_length=32, default="deterministic-v1")
    method = models.CharField(
        max_length=24,
        choices=Method.choices,
        default=Method.DETERMINISTIC,
    )
    severity = models.CharField(max_length=16, choices=Severity.choices)
    result = models.CharField(max_length=16, choices=Result.choices)
    title = models.CharField(max_length=300)
    summary = models.TextField(blank=True)
    impact = models.TextField(blank=True)
    recommendation = models.TextField(blank=True)
    affected_count = models.PositiveIntegerField(default=0)
    evidence = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "website_audit_findings"
        indexes = [
            models.Index(fields=("audit", "category", "severity"), name="website_finding_idx"),
            models.Index(fields=("audit", "check_key"), name="website_check_key_idx"),
        ]
