from __future__ import annotations

from django.db.models import Count
from rest_framework import serializers

from .models import NegativeEvent, NegativeIndexItem, NegativeIndexScan
from .scoring import risk_level


class NegativeIndexScanSummarySerializer(serializers.ModelSerializer):
    elapsed_seconds = serializers.SerializerMethodField()
    risk_level = serializers.SerializerMethodField()

    class Meta:
        model = NegativeIndexScan
        fields: tuple[str, ...] = (
            "id",
            "subject_id",
            "status",
            "stage",
            "provider",
            "ai_provider",
            "ai_model_key",
            "query_count",
            "provider_request_count",
            "provider_error_count",
            "raw_result_count",
            "unique_result_count",
            "candidate_count",
            "negative_item_count",
            "event_count",
            "high_risk_event_count",
            "recent_30d_event_count",
            "verified_item_count",
            "index_score",
            "risk_level",
            "factor_scores",
            "progress",
            "formula_version",
            "classifier_version",
            "stable_error_code",
            "elapsed_seconds",
            "started_at",
            "finished_at",
            "created_at",
        )

    def get_elapsed_seconds(self, obj):
        if obj.elapsed_ms is None:
            return None
        return round(obj.elapsed_ms / 1000, 2)

    def get_risk_level(self, obj):
        return risk_level(obj.index_score)


class NegativeIndexScanDetailSerializer(NegativeIndexScanSummarySerializer):
    category_distribution = serializers.SerializerMethodField()
    status_distribution = serializers.SerializerMethodField()

    class Meta(NegativeIndexScanSummarySerializer.Meta):
        fields: tuple[str, ...] = NegativeIndexScanSummarySerializer.Meta.fields + (
            "category_distribution",
            "status_distribution",
        )

    def get_category_distribution(self, obj):
        return list(
            obj.events.values("category").annotate(count=Count("id")).order_by("-count", "category")
        )

    def get_status_distribution(self, obj):
        return list(
            obj.events.values("status").annotate(count=Count("id")).order_by("-count", "status")
        )


class NegativeIndexItemSerializer(serializers.ModelSerializer):
    matched_queries = serializers.SerializerMethodField()

    class Meta:
        model = NegativeIndexItem
        fields: tuple[str, ...] = (
            "id",
            "original_url",
            "domain",
            "root_domain",
            "website",
            "title",
            "snippet",
            "published_at",
            "source_type",
            "authority_score",
            "relevance_score",
            "visibility_score",
            "freshness_score",
            "best_rank",
            "matched_query_count",
            "matched_queries",
            "rule_signal_score",
            "negative_confidence",
            "severity_score",
            "evidence_confidence",
            "category",
            "claim_type",
            "event_status",
            "event_title",
            "ai_summary",
            "classification_source",
            "verification_status",
            "verification_excerpt",
            "verification_error_code",
        )

    def get_matched_queries(self, obj):
        queries: list[str] = []
        seen: set[str] = set()
        rows = obj.hits.order_by("rank", "id").values_list("query", flat=True)
        for query in rows:
            if query not in seen:
                seen.add(query)
                queries.append(query)
            if len(queries) >= 20:
                break
        return queries


class NegativeEventSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = NegativeEvent
        fields: tuple[str, ...] = (
            "id",
            "category",
            "claim_type",
            "status",
            "title",
            "summary",
            "severity_score",
            "evidence_score",
            "visibility_score",
            "freshness_score",
            "current_risk",
            "source_count",
            "independent_domain_count",
            "first_seen_at",
            "last_seen_at",
        )


class NegativeEventDetailSerializer(NegativeEventSummarySerializer):
    sources = serializers.SerializerMethodField()

    class Meta(NegativeEventSummarySerializer.Meta):
        fields: tuple[str, ...] = NegativeEventSummarySerializer.Meta.fields + ("sources",)

    def get_sources(self, obj):
        items = obj.items.prefetch_related("hits").order_by(
            "-evidence_confidence",
            "best_rank",
            "id",
        )[:100]
        return NegativeIndexItemSerializer(items, many=True).data
