from rest_framework import serializers

from .models import WebsiteAudit, WebsiteAuditPage


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
            "image_count",
            "image_alt_missing_count",
            "internal_links_count",
            "external_links_count",
            "text_characters",
            "text_sample",
            "fetch_error",
            "fetched_at",
        )


class WebsiteAuditSerializer(serializers.ModelSerializer):
    subject_id = serializers.UUIDField(read_only=True)
    pages = WebsiteAuditPageSerializer(many=True, read_only=True)

    class Meta:
        model = WebsiteAudit
        fields = (
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
            "created_at",
            "pages",
        )
