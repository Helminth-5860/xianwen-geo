from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import date

from django.conf import settings
from django.core.cache import cache

from apps.source_index.provider import (
    BaiduSearchProvider as CanonicalBaiduSearchProvider,
)
from apps.source_index.provider import (
    SearchProvider,
    SearchProviderError,
    SearchResult,
    baidu_query_units,
    clean_text,
    truncate_baidu_query,
)


class BaiduSearchProvider:
    """Cached adapter over the canonical source-index Baidu provider.

    Credential resolution deliberately stays owned by apps.source_index.provider so
    negative-index cannot introduce a second Baidu credential path. On the live
    baseline this inherits the existing baidu_search credential resolver; older
    baselines retain their existing environment fallback behavior.
    """

    top_k = CanonicalBaiduSearchProvider.top_k

    def __init__(self):
        self.upstream = CanonicalBaiduSearchProvider()
        self.cache_ttl = int(getattr(settings, "SEARCH_DISCOVERY_CACHE_TTL_SECONDS", 300))

    def close(self):
        self.upstream.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def _cache_key(
        self,
        query: str,
        *,
        start_date: date | None,
        end_date: date | None,
    ) -> str:
        raw = json.dumps(
            {
                "provider": "canonical_baidu_search_v2",
                "query": query,
                "start": start_date.isoformat() if start_date else "",
                "end": end_date.isoformat() if end_date else "",
                "top_k": self.top_k,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return f"search-discovery:{digest}"

    def search(
        self,
        query: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[SearchResult]:
        safe_query = truncate_baidu_query(query)
        if not safe_query:
            return []

        cache_key = self._cache_key(
            safe_query,
            start_date=start_date,
            end_date=end_date,
        )
        if self.cache_ttl > 0:
            cached = cache.get(cache_key)
            if isinstance(cached, list):
                try:
                    return [SearchResult(**item) for item in cached if isinstance(item, dict)]
                except (TypeError, ValueError):
                    cache.delete(cache_key)

        results = self.upstream.search(
            safe_query,
            start_date=start_date,
            end_date=end_date,
        )
        if self.cache_ttl > 0:
            cache.set(
                cache_key,
                [asdict(item) for item in results],
                timeout=self.cache_ttl,
            )
        return results


__all__ = [
    "BaiduSearchProvider",
    "SearchProvider",
    "SearchProviderError",
    "SearchResult",
    "baidu_query_units",
    "clean_text",
    "truncate_baidu_query",
]
