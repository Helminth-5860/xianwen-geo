from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from typing import Protocol

import httpx
from django.conf import settings
from django.core.cache import cache


class SearchProviderError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    website: str
    snippet: str
    published_raw: str
    rank: int


class SearchProvider(Protocol):
    top_k: int

    def search(
        self,
        query: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[SearchResult]:
        ...


class BaiduSearchProvider:
    endpoint = "https://qianfan.baidubce.com/v2/ai_search/web_search"
    top_k = 50

    def __init__(self):
        self.api_key = getattr(settings, "BAIDU_SEARCH_API_KEY", "").strip()
        self.auth_header = getattr(settings, "BAIDU_SEARCH_AUTH_HEADER", "Authorization").strip()
        if not self.api_key:
            raise SearchProviderError("BAIDU_SEARCH_API_KEY_MISSING")
        if self.auth_header not in {"Authorization", "X-Appbuilder-Authorization"}:
            raise SearchProviderError("BAIDU_SEARCH_AUTH_HEADER_INVALID")
        timeout = float(
            getattr(
                settings,
                "SEARCH_DISCOVERY_REQUEST_TIMEOUT_SECONDS",
                getattr(settings, "SOURCE_INDEX_REQUEST_TIMEOUT_SECONDS", 12),
            )
        )
        self.cache_ttl = int(getattr(settings, "SEARCH_DISCOVERY_CACHE_TTL_SECONDS", 300))
        self.client = httpx.Client(timeout=httpx.Timeout(timeout))

    def close(self):
        self.client.close()

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
                "provider": "baidu_search_v2",
                "query": query,
                "start": start_date.isoformat() if start_date else "",
                "end": end_date.isoformat() if end_date else "",
                "top_k": self.top_k,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return "search-discovery:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()

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
        cache_key = self._cache_key(safe_query, start_date=start_date, end_date=end_date)
        if self.cache_ttl > 0:
            cached = cache.get(cache_key)
            if isinstance(cached, list):
                try:
                    return [SearchResult(**item) for item in cached if isinstance(item, dict)]
                except (TypeError, ValueError):
                    cache.delete(cache_key)

        body: dict = {
            "messages": [{"content": safe_query, "role": "user"}],
            "search_source": "baidu_search_v2",
            "resource_type_filter": [{"type": "web", "top_k": self.top_k}],
        }
        if start_date is not None and end_date is not None:
            body["search_filter"] = {
                "range": {
                    "page_time": {
                        "gte": start_date.isoformat(),
                        "lte": end_date.isoformat(),
                    }
                }
            }
        headers = {
            self.auth_header: f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = self.client.post(self.endpoint, json=body, headers=headers)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise SearchProviderError("BAIDU_SEARCH_NETWORK_ERROR", retryable=True) from exc
        if response.status_code == 429:
            raise SearchProviderError("BAIDU_SEARCH_RATE_LIMITED", retryable=True)
        if response.status_code in {500, 501, 502, 503, 504}:
            raise SearchProviderError("BAIDU_SEARCH_UPSTREAM_ERROR", retryable=True)
        if response.status_code in {401, 403}:
            raise SearchProviderError("BAIDU_SEARCH_AUTH_FAILED")
        if response.status_code >= 400:
            raise SearchProviderError("BAIDU_SEARCH_BAD_REQUEST")
        try:
            payload = response.json()
        except ValueError as exc:
            raise SearchProviderError("BAIDU_SEARCH_INVALID_JSON", retryable=True) from exc
        if payload.get("code") not in (None, "", 0, "0"):
            code_text = str(payload.get("code"))
            retryable = code_text in {"500", "501", "502", "429"}
            raise SearchProviderError("BAIDU_SEARCH_PROVIDER_ERROR", retryable=retryable)
        references = payload.get("references") or []
        results: list[SearchResult] = []
        for position, raw in enumerate(references, start=1):
            if not isinstance(raw, dict) or raw.get("type") not in (None, "", "web"):
                continue
            url = clean_text(raw.get("url"), max_length=4096)
            title = clean_text(raw.get("title"), max_length=1000)
            if not url or not title:
                continue
            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    website=clean_text(raw.get("website") or raw.get("web_anchor"), max_length=500),
                    snippet=clean_text(raw.get("snippet") or raw.get("content"), max_length=4000),
                    published_raw=clean_text(raw.get("date"), max_length=100),
                    rank=position,
                )
            )
        if self.cache_ttl > 0:
            cache.set(cache_key, [asdict(item) for item in results], timeout=self.cache_ttl)
        return results


def clean_text(value, *, max_length: int) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).replace("\x00", " ").split())
    return text[:max_length]


def baidu_query_units(text: str) -> int:
    return sum(1 if ord(char) < 128 else 2 for char in text)


def truncate_baidu_query(text: str, max_units: int = 72) -> str:
    compact = " ".join((text or "").split()).strip()
    if baidu_query_units(compact) <= max_units:
        return compact
    output: list[str] = []
    used = 0
    for char in compact:
        units = 1 if ord(char) < 128 else 2
        if used + units > max_units:
            break
        output.append(char)
        used += units
    return "".join(output).strip()
