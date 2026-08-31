from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.utils import timezone

from apps.search_discovery.engine import (
    AdaptiveSearchConfig,
    AdaptiveSearchPayload,
    run_adaptive_search,
)
from apps.search_discovery.provider import SearchProvider, SearchProviderError
from apps.search_discovery.subject_context import (
    SubjectSearchContext,
    build_subject_search_context,
)

from .models import NegativeIndexScan
from .queries import build_negative_queries


@dataclass
class NegativeScanPayload:
    context: SubjectSearchContext
    records: dict[str, dict]
    hits: list[dict]
    provider_requests: int
    provider_errors: int
    raw_results: int
    query_count: int
    limit_reached: bool
    partial: bool


def run_negative_search(
    scan: NegativeIndexScan,
    *,
    provider: SearchProvider,
) -> NegativeScanPayload:
    context = build_subject_search_context(scan.subject)
    initial_queries = build_negative_queries(
        context,
        max_queries=int(getattr(settings, "NEGATIVE_INDEX_MAX_QUERIES", 12)),
    )
    if not initial_queries:
        raise SearchProviderError("NEGATIVE_INDEX_SUBJECT_IDENTITY_MISSING")
    max_requests = min(30, int(getattr(settings, "NEGATIVE_INDEX_MAX_REQUESTS", 30)))

    NegativeIndexScan.objects.filter(pk=scan.pk).update(
        status=NegativeIndexScan.Status.RUNNING,
        stage=NegativeIndexScan.Stage.SEARCHING,
        started_at=scan.started_at or timezone.now(),
        query_count=len(initial_queries),
        progress={
            "queries_planned": len(initial_queries),
            "raw": 0,
            "unique": 0,
        },
    )

    def progress_callback(snapshot: dict) -> None:
        NegativeIndexScan.objects.filter(pk=scan.pk).update(
            provider_request_count=snapshot["provider_request_count"],
            provider_error_count=snapshot["provider_error_count"],
            raw_result_count=snapshot["raw_result_count"],
            unique_result_count=snapshot["unique_result_count"],
            query_count=snapshot["query_count"],
            progress=snapshot["progress"],
        )

    payload: AdaptiveSearchPayload = run_adaptive_search(
        initial_queries=initial_queries,
        provider=provider,
        config=AdaptiveSearchConfig(
            search_budget_seconds=int(
                getattr(settings, "NEGATIVE_INDEX_SEARCH_BUDGET_SECONDS", 120)
            ),
            max_requests=max_requests,
            concurrency=int(getattr(settings, "NEGATIVE_INDEX_SEARCH_CONCURRENCY", 3)),
            min_requests=min(
                max_requests,
                int(getattr(settings, "NEGATIVE_INDEX_MIN_REQUESTS", 9)),
            ),
            stop_yield_ratio=float(getattr(settings, "NEGATIVE_INDEX_STOP_YIELD_RATIO", 0.08)),
            low_yield_batches=int(getattr(settings, "NEGATIVE_INDEX_LOW_YIELD_BATCHES", 3)),
            error_prefix="NEGATIVE_INDEX",
        ),
        progress_callback=progress_callback,
    )
    return NegativeScanPayload(
        context=context,
        records=payload.records,
        hits=payload.hits,
        provider_requests=payload.provider_requests,
        provider_errors=payload.provider_errors,
        raw_results=payload.raw_results,
        query_count=payload.query_count,
        limit_reached=payload.limit_reached,
        partial=payload.partial,
    )
