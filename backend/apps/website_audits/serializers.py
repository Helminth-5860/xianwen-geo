from rest_framework import serializers

from .models import (
    WebsiteAudit,
    WebsiteAuditBrowserSnapshot,
    WebsiteAuditFinding,
    WebsiteAuditPage,
)


class WebsiteAuditCreateSerializer(serializers.Serializer):
    url = serializers.URLField(max_length=4096)


class WebsiteAuditPageSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebsiteAuditPage
        fields = (
            "id",
            "url",
            "final_url",
            "source",
            "depth",
            "http_status",
            "content_type",
            "response_ms",
            "response_bytes",
            "redirect_count",
            "title",
            "meta_description",
            "canonical_url",
            "robots_meta",
            "html_lang",
            "viewport",
            "headings",
            "open_graph",
            "twitter_card",
            "schema_types",
            "schema_entities",
            "jsonld_block_count",
            "jsonld_invalid_count",
            "image_count",
            "image_alt_missing_count",
            "paragraph_count",
            "list_count",
            "table_count",
            "internal_links_count",
            "external_links_count",
            "text_characters",
            "text_sample",
            "fetch_error",
            "fetched_at",
        )


class WebsiteAuditBrowserSnapshotSerializer(serializers.ModelSerializer):
    page_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = WebsiteAuditBrowserSnapshot
        fields = (
            "id",
            "page_id",
            "profile",
            "status",
            "final_url",
            "navigation_ms",
            "ttfb_ms",
            "dom_content_loaded_ms",
            "load_ms",
            "fcp_ms",
            "lcp_ms",
            "cls",
            "tbt_ms",
            "request_count",
            "failed_request_count",
            "blocked_request_count",
            "transfer_bytes",
            "cross_host_request_count",
            "cross_host_transfer_bytes",
            "resource_summary",
            "console_error_count",
            "page_error_count",
            "dom_nodes",
            "rendered_html_characters",
            "rendered_text_characters",
            "static_text_characters",
            "text_delta",
            "text_growth_ratio",
            "rendered_title",
            "rendered_meta_description",
            "rendered_canonical_url",
            "rendered_schema_types",
            "rendered_heading_counts",
            "visible_image_count",
            "images_without_alt",
            "failure_code",
            "evidence",
            "created_at",
        )


class WebsiteAuditFindingSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebsiteAuditFinding
        fields = (
            "id",
            "category",
            "dimension",
            "check_key",
            "rule_version",
            "method",
            "severity",
            "result",
            "title",
            "summary",
            "impact",
            "recommendation",
            "affected_count",
            "evidence",
            "created_at",
        )


_SUMMARY_FIELDS = (
    "id",
    "subject_id",
    "root_url",
    "root_host",
    "status",
    "max_pages",
    "discovered_count",
    "selected_count",
    "fetched_count",
    "failed_count",
    "internal_link_count",
    "external_link_count",
    "robots_url",
    "robots_status",
    "sitemap_urls",
    "stable_error_code",
    "started_at",
    "finished_at",
    "browser_status",
    "browser_profiles",
    "browser_selected_count",
    "browser_completed_count",
    "browser_failed_count",
    "browser_error_code",
    "browser_started_at",
    "browser_finished_at",
    "semantic_status",
    "semantic_provider_key",
    "semantic_model_id",
    "semantic_prompt_version",
    "semantic_page_count",
    "semantic_question_count",
    "semantic_scores",
    "semantic_error_code",
    "semantic_started_at",
    "semantic_finished_at",
    "created_at",
)

_SEMANTIC_DETAIL_FIELDS = (
    "semantic_runtime_version",
    "semantic_result",
    "semantic_input_tokens",
    "semantic_output_tokens",
    "semantic_total_tokens",
    "semantic_latency_ms",
)


class WebsiteAuditSummarySerializer(serializers.ModelSerializer):
    subject_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = WebsiteAudit
        fields = _SUMMARY_FIELDS


class WebsiteAuditDetailSerializer(serializers.ModelSerializer):
    subject_id = serializers.UUIDField(read_only=True)
    pages = WebsiteAuditPageSerializer(many=True, read_only=True)
    browser_snapshots = WebsiteAuditBrowserSnapshotSerializer(many=True, read_only=True)
    findings = WebsiteAuditFindingSerializer(many=True, read_only=True)

    class Meta:
        model = WebsiteAudit
        fields = _SUMMARY_FIELDS + _SEMANTIC_DETAIL_FIELDS + (
            "pages",
            "browser_snapshots",
            "findings",
        )
