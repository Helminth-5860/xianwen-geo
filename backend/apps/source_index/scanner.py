from __future__ import annotations

import re
import time as time_module
from collections import deque
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, timedelta

from django.conf import settings
from django.utils import timezone

from apps.keywords.models import Keyword
from apps.subjects.models import Subject, SubjectBusinessProfile, SubjectName, SubjectProduct

from .models import SourceIndexScan
from .provider import SearchProvider, SearchProviderError, SearchResult, truncate_baidu_query
from .scoring import normalize_url, parse_provider_datetime


@dataclass(frozen=True)
class SearchTask:
    query: str
    range_start: date | None = None
    range_end: date | None = None
    depth: int = 0

    @property
    def key(self) -> tuple[str, date | None, date | None]:
        return self.query, self.range_start, self.range_end


@dataclass(frozen=True)
class SubjectSearchContext:
    official_name: str
    anchors: list[str]
    products: list[str]
    keywords: list[str]
    self_domains: set[str]


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


def build_subject_search_context(subject: Subject) -> SubjectSearchContext:
    version = subject.current_version
    official_name = (version.official_name if version else "").strip()
    profile = SubjectBusinessProfile.objects.filter(subject=subject).first()
    brand_name = (profile.brand_name if profile else "").strip()

    anchors: list[str] = []
    for value in (official_name, brand_name):
        _append_unique(anchors, value)
    if version is not None:
        name_values = SubjectName.objects.filter(subject_version=version).values_list(
            "display_value", flat=True
        )
        for value in name_values:
            _append_unique(anchors, value)
    if not official_name and anchors:
        official_name = anchors[0]

    products: list[str] = []
    if version is not None:
        product_qs = SubjectProduct.objects.filter(subject_version=version).order_by(
            "-include_in_mention", "display_value"
        )
        for value in product_qs.values_list("display_value", flat=True)[:8]:
            _append_unique(products, value)

    keywords: list[str] = []
    try:
        keyword_set = subject.keyword_set
    except Exception:
        keyword_set = None
    if keyword_set is not None and keyword_set.current_version_id:
        keyword_qs = Keyword.objects.filter(
            keyword_set_version_id=keyword_set.current_version_id
        ).order_by("sort_order", "id")
        for value in keyword_qs.values_list("text", flat=True)[:12]:
            _append_unique(keywords, value)

    self_domains = _extract_self_domains(version.field_values if version else {})
    return SubjectSearchContext(
        official_name=official_name,
        anchors=anchors,
        products=products,
        keywords=keywords,
        self_domains=self_domains,
    )


def build_initial_queries(context: SubjectSearchContext, max_queries: int = 12) -> list[str]:
    queries: list[str] = []
    if not context.anchors:
        return queries
    official = context.official_name or context.anchors[0]
    primary = _primary_anchor(context.anchors, official)
    _append_query(queries, official)
    if primary != official:
        _append_query(queries, primary)
    for alias in context.anchors:
        if len(queries) >= 4:
            break
        _append_query(queries, alias)
    for suffix in ("新闻", "报道", "媒体"):
        _append_query(queries, f"{primary} {suffix}")
    for product in context.products[:2]:
        _append_query(queries, f"{primary} {product}")
    for keyword in context.keywords:
        if len(queries) >= max_queries:
            break
        if any(anchor and anchor.casefold() in keyword.casefold() for anchor in context.anchors):
            _append_query(queries, keyword)
        else:
            _append_query(queries, f"{primary} {keyword}")
    return queries[:max_queries]


def run_adaptive_scan(scan: SourceIndexScan, *, provider: SearchProvider) -> ScanPayload:
    context = build_subject_search_context(scan.subject)
    initial_queries = build_initial_queries(context, max_queries=12)
    if not initial_queries:
        raise SearchProviderError("SOURCE_INDEX_SUBJECT_IDENTITY_MISSING")

    started = time_module.monotonic()
    search_budget = int(getattr(settings, "SOURCE_INDEX_SEARCH_BUDGET_SECONDS", 260))
    max_requests = min(30, int(getattr(settings, "SOURCE_INDEX_MAX_REQUESTS", 30)))
    batch_size = int(getattr(settings, "SOURCE_INDEX_SEARCH_CONCURRENCY", 3))
    min_requests = min(max_requests, int(getattr(settings, "SOURCE_INDEX_MIN_REQUESTS", 12)))
    stop_ratio = float(getattr(settings, "SOURCE_INDEX_STOP_YIELD_RATIO", 0.08))
    low_yield_batches_needed = int(getattr(settings, "SOURCE_INDEX_LOW_YIELD_BATCHES", 3))

    queue: deque[SearchTask] = deque(SearchTask(query=query) for query in initial_queries)
    seen_tasks = {task.key for task in queue}
    records: dict[str, dict] = {}
    hit_keys: set[tuple[str, str, date | None, date | None]] = set()
    hits: list[dict] = []
    provider_requests = 0
    provider_errors = 0
    raw_results = 0
    low_yield_batches = 0
    partial = False
    hit_limit = False

    SourceIndexScan.objects.filter(pk=scan.pk).update(
        status=SourceIndexScan.Status.RUNNING,
        stage=SourceIndexScan.Stage.SEARCHING,
        started_at=timezone.now(),
        query_count=len(initial_queries),
        progress={"queries_planned": len(initial_queries), "raw": 0, "unique": 0},
    )

    while queue:
        if time_module.monotonic() - started >= search_budget or provider_requests >= max_requests:
            hit_limit = True
            break
        remaining_requests = max_requests - provider_requests
        current_batch: list[SearchTask] = []
        while queue and len(current_batch) < min(batch_size, remaining_requests):
            current_batch.append(queue.popleft())
        if not current_batch:
            break
        attempt_budgets = _allocate_attempt_budgets(remaining_requests, len(current_batch))

        batch_started = time_module.monotonic()
        outcomes = []
        with ThreadPoolExecutor(max_workers=len(current_batch)) as executor:
            future_map = {
                executor.submit(
                    _search_with_retry,
                    provider,
                    task,
                    started,
                    search_budget,
                    max_attempts,
                ): task
                for task, max_attempts in zip(current_batch, attempt_budgets, strict=True)
            }
            for future in as_completed(future_map):
                task = future_map[future]
                try:
                    results, attempts, error_code = future.result()
                except SearchProviderError:
                    raise
                except Exception:
                    results, attempts, error_code = [], 1, "BAIDU_SEARCH_UNEXPECTED_ERROR"
                provider_requests += attempts
                if error_code:
                    provider_errors += 1
                    partial = True
                outcomes.append((task, results, error_code))

        batch_raw = 0
        batch_new = 0
        for task, results, error_code in outcomes:
            if error_code and not results:
                continue
            batch_raw += len(results)
            raw_results += len(results)
            branch_new = 0
            for result in results:
                normalized = normalize_url(result.url)
                if normalized is None:
                    continue
                normalized_url, domain, root = normalized
                record = records.get(normalized_url)
                published_at = parse_provider_datetime(result.published_raw)
                if record is None:
                    record = {
                        "original_url": result.url,
                        "normalized_url": normalized_url,
                        "domain": domain,
                        "root_domain": root,
                        "website": result.website,
                        "title": result.title,
                        "snippet": result.snippet,
                        "published_at": published_at,
                        # A rank from a time-sliced search is not equivalent to an unfiltered
                        # search position. Sources discovered only through a slice are recorded
                        # as 50+ for visibility scoring while the exact slice rank remains in hits.
                        "best_rank": (
                            result.rank if task.range_start is None else provider.top_k + 1
                        ),
                        "matched_queries": set(),
                    }
                    records[normalized_url] = record
                    branch_new += 1
                    batch_new += 1
                else:
                    if task.range_start is None:
                        record["best_rank"] = min(record["best_rank"], result.rank)
                    if not record["published_at"] and published_at:
                        record["published_at"] = published_at
                    if len(result.snippet) > len(record["snippet"]):
                        record["snippet"] = result.snippet
                    if not record["website"] and result.website:
                        record["website"] = result.website
                record["matched_queries"].add(task.query)
                hit_key = (normalized_url, task.query, task.range_start, task.range_end)
                if hit_key not in hit_keys:
                    hit_keys.add(hit_key)
                    hits.append(
                        {
                            "normalized_url": normalized_url,
                            "query": task.query,
                            "rank": result.rank,
                            "range_start": task.range_start,
                            "range_end": task.range_end,
                        }
                    )

            branch_yield = branch_new / max(1, len(results))
            saturated = len(results) >= provider.top_k
            # Once a bounded date slice itself is full, keep splitting it even when many of
            # its current top results duplicate the parent search. Hidden lower-ranked URLs
            # can only surface after the saturated slice is narrowed further. Global marginal
            # yield still stops the overall scan when additional work stops producing value.
            should_expand = saturated and (
                task.range_start is not None or branch_yield >= stop_ratio
            )
            if should_expand:
                for expanded in _expand_task(task):
                    if expanded.key not in seen_tasks:
                        seen_tasks.add(expanded.key)
                        queue.append(expanded)

        batch_yield = batch_new / max(1, batch_raw)
        if provider_requests >= min_requests:
            if batch_raw == 0 or batch_yield < stop_ratio:
                low_yield_batches += 1
            else:
                low_yield_batches = 0
            if low_yield_batches >= low_yield_batches_needed:
                queue.clear()

        SourceIndexScan.objects.filter(pk=scan.pk).update(
            provider_request_count=provider_requests,
            provider_error_count=provider_errors,
            raw_result_count=raw_results,
            unique_result_count=len(records),
            query_count=len({hit["query"] for hit in hits} | set(initial_queries)),
            progress={
                "queries_planned": len(seen_tasks),
                "queries_remaining": len(queue),
                "raw": raw_results,
                "unique": len(records),
                "batch_new": batch_new,
                "batch_yield": round(batch_yield, 4),
            },
        )

        # Enforce the provider's common 3-QPS baseline without wasting time when
        # requests themselves are slow.
        minimum_batch_window = len(current_batch) / max(1, batch_size)
        elapsed_batch = time_module.monotonic() - batch_started
        if elapsed_batch < minimum_batch_window:
            time_module.sleep(minimum_batch_window - elapsed_batch)

    return ScanPayload(
        context=context,
        records=records,
        hits=hits,
        provider_requests=provider_requests,
        provider_errors=provider_errors,
        raw_results=raw_results,
        query_count=len({hit["query"] for hit in hits} | set(initial_queries)),
        limit_reached=hit_limit,
        partial=partial,
    )


def _search_with_retry(
    provider: SearchProvider,
    task: SearchTask,
    scan_started: float,
    search_budget: int,
    max_attempts: int = 3,
) -> tuple[list[SearchResult], int, str]:
    attempts = 0
    last_code = ""
    for retry_no in range(max_attempts):
        if time_module.monotonic() - scan_started >= search_budget:
            return [], attempts, "SOURCE_INDEX_SEARCH_BUDGET_EXHAUSTED"
        attempts += 1
        try:
            return (
                provider.search(
                    task.query,
                    start_date=task.range_start,
                    end_date=task.range_end,
                ),
                attempts,
                "",
            )
        except SearchProviderError as exc:
            last_code = exc.code
            if not exc.retryable:
                raise
            if retry_no >= max_attempts - 1:
                return [], attempts, last_code
            time_module.sleep(min(2.0, 0.5 * (2**retry_no)))
    return [], attempts, last_code or "BAIDU_SEARCH_FAILED"


def _allocate_attempt_budgets(remaining_requests: int, task_count: int) -> list[int]:
    if task_count <= 0:
        return []
    budgets = [1] * task_count
    extra = max(0, remaining_requests - task_count)
    for index in range(task_count):
        if extra <= 0:
            break
        addition = min(2, extra)
        budgets[index] += addition
        extra -= addition
    return budgets


def _expand_task(task: SearchTask) -> Iterable[SearchTask]:
    today = timezone.localdate()
    if task.range_start is None or task.range_end is None:
        boundaries = [
            date(1995, 1, 1),
            today - timedelta(days=3650),
            today - timedelta(days=1095),
            today - timedelta(days=365),
            today - timedelta(days=180),
            today - timedelta(days=30),
            today,
        ]
        normalized: list[date] = []
        for value in boundaries:
            value = min(value, today)
            if not normalized or value > normalized[-1]:
                normalized.append(value)
        for start, end_exclusive in zip(normalized, normalized[1:], strict=False):
            end = end_exclusive - timedelta(days=1)
            if start <= end:
                yield SearchTask(task.query, start, end, depth=1)
        if normalized and normalized[-1] <= today:
            yield SearchTask(task.query, normalized[-1], today, depth=1)
        return

    span = (task.range_end - task.range_start).days
    if span < 14 or task.depth >= 8:
        return
    midpoint = task.range_start + timedelta(days=span // 2)
    if midpoint <= task.range_start or midpoint >= task.range_end:
        return
    yield SearchTask(task.query, task.range_start, midpoint, depth=task.depth + 1)
    yield SearchTask(task.query, midpoint + timedelta(days=1), task.range_end, depth=task.depth + 1)


def _primary_anchor(anchors: list[str], official: str) -> str:
    candidates = [value for value in anchors if 2 <= len(value) <= 24 and value != official]
    if candidates:
        return min(candidates, key=len)
    return official


def _append_query(queries: list[str], value: str):
    candidate = truncate_baidu_query(value)
    if not candidate:
        return
    key = candidate.casefold()
    if all(existing.casefold() != key for existing in queries):
        queries.append(candidate)


def _append_unique(values: list[str], value: str):
    candidate = " ".join((value or "").split()).strip()
    if len(candidate) < 2:
        return
    key = candidate.casefold()
    if all(existing.casefold() != key for existing in values):
        values.append(candidate)


def _extract_self_domains(field_values) -> set[str]:
    domains: set[str] = set()

    def visit(value):
        if isinstance(value, dict):
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, str):
            for match in re.findall(r"https?://[^\s,，;；]+", value):
                normalized = normalize_url(match.rstrip(".)）]】"))
                if normalized:
                    domains.add(normalized[1])
                    domains.add(normalized[2])

    visit(field_values)
    return domains
