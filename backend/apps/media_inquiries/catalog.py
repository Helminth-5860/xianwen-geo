from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings

from .exceptions import PaidMediaCatalogUnavailable, PaidMediaInputInvalid


@dataclass(frozen=True)
class PaidMediaCatalogItem:
    id: str
    name: str
    price_cents: int
    url: str | None
    domain: str | None
    logo_path: str | None
    category: str | None = None
    region: str | None = None
    portal_type: str | None = None

    def public_payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "price_cents": self.price_cents,
            "url": self.url,
            "domain": self.domain,
            "logo_path": self.logo_path,
        }

    def inquiry_snapshot(self) -> dict[str, object]:
        return {
            **self.public_payload(),
            "price": f"{Decimal(self.price_cents) / Decimal(100):.2f}",
        }


@dataclass(frozen=True)
class PaidMediaCatalog:
    version: int
    items: tuple[PaidMediaCatalogItem, ...]
    by_id: dict[str, PaidMediaCatalogItem]


def _catalog_path() -> Path:
    configured = str(getattr(settings, "PAID_MEDIA_CATALOG_PATH", "")).strip()
    if configured:
        return Path(configured).resolve()
    return (settings.BASE_DIR.parent / "config" / "paid-media-catalog.json").resolve()


def _catalog_url(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 2000:
        raise PaidMediaCatalogUnavailable
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise PaidMediaCatalogUnavailable from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        raise PaidMediaCatalogUnavailable
    return value


def _catalog_item(raw: object) -> PaidMediaCatalogItem:
    if not isinstance(raw, dict):
        raise PaidMediaCatalogUnavailable
    item_id = raw.get("id")
    name = raw.get("name")
    price_cents = raw.get("price_cents")
    url = _catalog_url(raw.get("url"))
    domain = raw.get("domain")
    logo_path = raw.get("logo_path")
    category = raw.get("category")
    region = raw.get("region")
    portal_type = raw.get("portal_type")
    if (
        not isinstance(item_id, str)
        or not item_id.strip()
        or len(item_id) > 128
        or not isinstance(name, str)
        or not name.strip()
        or len(name) > 300
        or isinstance(price_cents, bool)
        or not isinstance(price_cents, int)
        or price_cents < 0
        or not isinstance(domain, str)
        or len(domain) > 255
        or (logo_path is not None and (not isinstance(logo_path, str) or len(logo_path) > 500))
        or (category is not None and (not isinstance(category, str) or len(category) > 100))
        or (region is not None and (not isinstance(region, str) or len(region) > 100))
        or (
            portal_type is not None and (not isinstance(portal_type, str) or len(portal_type) > 100)
        )
    ):
        raise PaidMediaCatalogUnavailable
    return PaidMediaCatalogItem(
        id=item_id.strip(),
        name=name.strip(),
        price_cents=price_cents,
        url=url,
        domain=domain.strip() or None,
        logo_path=logo_path or None,
        category=category.strip() or None if isinstance(category, str) else None,
        region=region.strip() or None if isinstance(region, str) else None,
        portal_type=portal_type.strip() or None if isinstance(portal_type, str) else None,
    )


@lru_cache(maxsize=1)
def paid_media_catalog() -> PaidMediaCatalog:
    path = _catalog_path()
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PaidMediaCatalogUnavailable from exc
    version: object
    rows: object
    if isinstance(raw, list):
        version = 1
        rows = raw
    elif isinstance(raw, dict):
        version = raw.get("version", 1)
        rows = raw.get("items")
    else:
        raise PaidMediaCatalogUnavailable
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise PaidMediaCatalogUnavailable
    if not isinstance(rows, list) or not rows:
        raise PaidMediaCatalogUnavailable
    items = tuple(_catalog_item(row) for row in rows)
    by_id = {item.id: item for item in items}
    if len(by_id) != len(items):
        raise PaidMediaCatalogUnavailable
    return PaidMediaCatalog(version=version, items=items, by_id=by_id)


def clear_paid_media_catalog_cache() -> None:
    paid_media_catalog.cache_clear()


def search_paid_media_catalog(search: str) -> tuple[PaidMediaCatalogItem, ...]:
    catalog = paid_media_catalog()
    query = search.strip().casefold()
    if not query:
        return catalog.items
    if len(query) > 200:
        raise PaidMediaInputInvalid("PAID_MEDIA_SEARCH_TOO_LONG", "搜索内容最多可填写 200 个字。")
    return tuple(
        item
        for item in catalog.items
        if query in item.name.casefold()
        or (item.domain is not None and query in item.domain.casefold())
        or (item.url is not None and query in item.url.casefold())
    )
