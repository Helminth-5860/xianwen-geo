from __future__ import annotations

from django.db.models import Avg, Count, Max, Min, Q
from rest_framework import serializers

from .models import SourceIndexItem, SourceIndexScan


class SourceIndexScanSummarySerializer(serializers.ModelSerializer):
    elapsed_seconds = serializers.SerializerMethodField()

    class Meta:
        model = SourceIndexScan
        fields = (
            "id",
            "subject_id",
            "status",
            "stage",
            "provider",
            "query_count",
            "provider_request_count",
            "provider_error_count",
            "raw_result_count",
            "unique_result_count",
            "public_source_count",
            "independent_domain_count",
            "news_media_count",
            "high_weight_count",
            "recent_30d_count",
            "index_score",
            "factor_scores",
            "progress",
            "formula_version",
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


class SourceIndexScanDetailSerializer(SourceIndexScanSummarySerializer):
    source_type_distribution = serializers.SerializerMethodField()
    query_coverage = serializers.SerializerMethodField()
    top_sources = serializers.SerializerMethodField()

    class Meta(SourceIndexScanSummarySerializer.Meta):
        fields = SourceIndexScanSummarySerializer.Meta.fields + (
            "source_type_distribution",
            "query_coverage",
            "top_sources",
        )

    def get_source_type_distribution(self, obj):
        rows = obj.items.values("source_type").annotate(count=Count("id")).order_by("-count")
        return list(rows)

    def get_query_coverage(self, obj):
        rows = (
            obj.hits.values("query")
            .annotate(
                source_count=Count("item_id", distinct=True),
                independent_source_count=Count("item__root_domain", distinct=True),
                # Only an unbounded search position can be presented as the query's
                # best visible position. A rank from a date slice is local to that
                # slice and must not masquerade as a global/natural search rank.
                best_rank=Min(
                    "rank",
                    filter=Q(range_start__isnull=True, range_end__isnull=True),
                ),
            )
            .order_by("-source_count", "query")[:30]
        )
        return list(rows)

    def get_top_sources(self, obj):
        rows = (
            obj.items.values("root_domain", "source_type")
            .annotate(
                source_count=Count("id"),
                average_weight=Avg("source_weight"),
                highest_weight=Max("source_weight"),
            )
            .order_by("-source_count", "-highest_weight")[:20]
        )
        return [
            {
                **row,
                "average_weight": round(float(row["average_weight"]), 2),
                "highest_weight": round(float(row["highest_weight"]), 2),
            }
            for row in rows
        ]


class SourceIndexItemSerializer(serializers.ModelSerializer):
    matched_queries = serializers.SerializerMethodField()

    class Meta:
        model = SourceIndexItem
        fields = (
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
            "source_weight",
            "best_rank",
            "matched_query_count",
            "matched_queries",
            "repost_cluster_id",
            "score_version",
        )

    def get_matched_queries(self, obj):
        queries: list[str] = []
        seen: set[str] = set()
        for query in obj.hits.order_by("rank", "id").values_list("query", flat=True):
            if query in seen:
                continue
            seen.add(query)
            queries.append(query)
            if len(queries) >= 20:
                break
        return queries
