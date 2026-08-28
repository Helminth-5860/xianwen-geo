from __future__ import annotations

import time as time_module
from collections import deque
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, timedelta

from django.utils import timezone

from .normalization import normalize_url, parse_provider_datetime
from .provider import SearchProvider, SearchProviderError, SearchResult


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
class AdaptiveSearchConfig:
    search_budget_seconds: int
    max_requests: int
    concurrency: int
    min_requests: int
    stop_yield_ratio: float
    low_yield_batches: int
    error_prefix: str


@dataclass
class AdaptiveSearchPayload:
    records: dict[str, dict]
    hits: list[dict]
    provider_requests: int
    provider_errors: int
    raw_results: int
    query_count: int
    limit_reached: bool
    partial: bool


ProgressCallback = Callable[[dict], None]


def run_adaptive_search(*, initial_queries: list[str], provider: SearchProvider, config: AdaptiveSearchConfig, progress_callback: ProgressCallback | None = None) -> AdaptiveSearchPayload:
    started = time_module.monotonic()
    queue: deque[SearchTask] = deque(SearchTask(query=query) for query in initial_queries)
    seen_tasks = {task.key for task in queue}
    records: dict[str, dict] = {}
    hit_keys: set[tuple[str, str, date | None, date | None]] = set()
    hits: list[dict] = []
    provider_requests = provider_errors = raw_results = low_yield_batches = 0
    partial = hit_limit = False
    while queue:
        if time_module.monotonic() - started >= config.search_budget_seconds or provider_requests >= config.max_requests:
            hit_limit = True
            break
        remaining_requests = config.max_requests - provider_requests
        current_batch: list[SearchTask] = []
        while queue and len(current_batch) < min(config.concurrency, remaining_requests):
            current_batch.append(queue.popleft())
        if not current_batch:
            break
        attempt_budgets = _allocate_attempt_budgets(remaining_requests, len(current_batch))
        batch_started = time_module.monotonic()
        outcomes = []
        with ThreadPoolExecutor(max_workers=len(current_batch)) as executor:
            future_map = {executor.submit(_search_with_retry, provider, task, started, config.search_budget_seconds, config.error_prefix, max_attempts): task for task, max_attempts in zip(current_batch, attempt_budgets, strict=True)}
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
        batch_raw = batch_new = 0
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
                    record = {"original_url": result.url, "normalized_url": normalized_url, "domain": domain, "root_domain": root, "website": result.website, "title": result.title, "snippet": result.snippet, "published_at": published_at, "best_rank": result.rank if task.range_start is None else provider.top_k + 1, "matched_queries": set()}
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
                    hits.append({"normalized_url": normalized_url, "query": task.query, "rank": result.rank, "range_start": task.range_start, "range_end": task.range_end})
            branch_yield = branch_new / max(1, len(results))
            if len(results) >= provider.top_k and (task.range_start is not None or branch_yield >= config.stop_yield_ratio):
                for expanded in _expand_task(task):
                    if expanded.key not in seen_tasks:
                        seen_tasks.add(expanded.key)
                        queue.append(expanded)
        batch_yield = batch_new / max(1, batch_raw)
        if provider_requests >= config.min_requests:
            if batch_raw == 0 or batch_yield < config.stop_yield_ratio:
                low_yield_batches += 1
            else:
                low_yield_batches = 0
            if low_yield_batches >= config.low_yield_batches:
                queue.clear()
        if progress_callback is not None:
            progress_callback({"provider_request_count": provider_requests, "provider_error_count": provider_errors, "raw_result_count": raw_results, "unique_result_count": len(records), "query_count": len({hit["query"] for hit in hits} | set(initial_queries)), "progress": {"queries_planned": len(seen_tasks), "queries_remaining": len(queue), "raw": raw_results, "unique": len(records), "batch_new": batch_new, "batch_yield": round(batch_yield, 4)}})
        minimum_batch_window = len(current_batch) / max(1, config.concurrency)
        elapsed_batch = time_module.monotonic() - batch_started
        if elapsed_batch < minimum_batch_window:
            time_module.sleep(minimum_batch_window - elapsed_batch)
    return AdaptiveSearchPayload(records=records, hits=hits, provider_requests=provider_requests, provider_errors=provider_errors, raw_results=raw_results, query_count=len({hit["query"] for hit in hits} | set(initial_queries)), limit_reached=hit_limit, partial=partial)


def _search_with_retry(provider: SearchProvider, task: SearchTask, scan_started: float, search_budget: int, error_prefix: str, max_attempts: int = 3) -> tuple[list[SearchResult], int, str]:
    attempts = 0
    last_code = ""
    for retry_no in range(max_attempts):
        if time_module.monotonic() - scan_started >= search_budget:
            return [], attempts, f"{error_prefix}_SEARCH_BUDGET_EXHAUSTED"
        attempts += 1
        try:
            return provider.search(task.query, start_date=task.range_start, end_date=task.range_end), attempts, ""
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
        boundaries = [date(1995, 1, 1), today - timedelta(days=3650), today - timedelta(days=1095), today - timedelta(days=365), today - timedelta(days=180), today - timedelta(days=30), today]
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
