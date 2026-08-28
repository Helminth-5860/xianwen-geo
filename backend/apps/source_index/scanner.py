from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.utils import timezone

from apps.search_discovery.engine import (
    AdaptiveSearchConfig,
    AdaptiveSearchPayload,
    SearchTask,
    _expand_task,
    run_adaptive_search,
)
from apps.search_discovery.subject_context import (
    SubjectSearchContext,
    append_query,
    build_subject_search_context,
    primary_anchor,
)

from .models import SourceIndexScan
from .provider import SearchProvider, SearchProviderError

__all__ = [
    "ScanPayload",
    "SearchTask",
    "SubjectSearchContext",
    "_expand_task",
    "build_initial_queries",
    "build_subject_search_context",
    "run_adaptive_scan",
]


@dataclass
class ScanPayload:
    context: SubjectSearchContext
    records: dict[str, dict]
    hits: list[dict]
    provider_requests: int
    provider_errors: int
    raw_results: int
    query_count: int
    limit_reached: bool
    partial: bool


def build_initial_queries(
    context: SubjectSearchContext, max_queries: int = 12
) -> list[str]:
    queries: list[str] = []
    if not context.anchors:
        return queries
    official = context.official_name or context.anchors[0]
    primary = primary_anchor(context.anchors, official)
    append_query(queries, official)
    if primary != official:
        append_query(queries, primary)
    for alias in context.anchors:
        if len(queries) >= 4:
            break
        append_query(queries, alias)
    for suffix in ("新闻", "报道", "媒体"):
        append_query(queries, f"{primary} {suffix}")
    for product in context.products[:2]:
        append_query(queries, f"{primary} {product}")
    for keyword in context.keywords:
        if len(queries) >= max_queries:
            break
        if any(
            anchor and anchor.casefold() in keyword.casefold()
            for anchor in context.anchors
        ):
            append_query(queries, keyword)
        else:
            append_query(queries, f"{primary} {keyword}")
    return queries[:max_queries]


def run_adaptive_scan(
    scan: SourceIndexScan, *, provider: SearchProvider
) -> ScanPayload:
    context = build_subject_search_context(scan.subject)
    initial_queries = build_initial_queries(context, max_queries=12)
    if not initial_queries:
        raise SearchProviderError("SOURCE_INDEX_SUBJECT_IDENTITY_MISSING")

    SourceIndexScan.objects.filter(pk=scan.pk).update(
        status=SourceIndexScan.Status.RUNNING,
        stage=SourceIndexScan.Stage.SEARCHING,
        started_at=scan.started_at or timezone.now(),
        query_count=len(initial_queries),
        progress={
            "queries_planned": len(initial_queries),
            "raw": 0,
            "unique": 0,
        },
    )

    def progress_callback(snapshot: dict) -> None:
        SourceIndexScan.objects.filter(pk=scan.pk).update(
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
                getattr(settings, "SOURCE_INDEX_SEARCH_BUDGET_SECONDS", 260)
            ),
            max_requests=int(getattr(settings, "SOURCE_INDEX_MAX_REQUESTS", 200)),
            concurrency=int(
                getattr(settings, "SOURCE_INDEX_SEARCH_CONCURRENCY", 3)
            ),
            min_requests=int(getattr(settings, "SOURCE_INDEX_MIN_REQUESTS", 12)),
            stop_yield_ratio=float(
                getattr(settings, "SOURCE_INDEX_STOP_YIELD_RATIO", 0.08)
            ),
            low_yield_batches=int(
                getattr(settings, "SOURCE_INDEX_LOW_YIELD_BATCHES", 3)
            ),
            error_prefix="SOURCE_INDEX",
        ),
        progress_callback=progress_callback,
    )
    return ScanPayload(
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
