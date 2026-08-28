from __future__ import annotations

import re
from dataclasses import dataclass

from apps.keywords.models import Keyword
from apps.subjects.models import (
    Subject,
    SubjectBusinessProfile,
    SubjectName,
    SubjectProduct,
)

from .normalization import normalize_url
from .provider import truncate_baidu_query


@dataclass(frozen=True)
class SubjectSearchContext:
    official_name: str
    anchors: list[str]
    products: list[str]
    keywords: list[str]
    self_domains: set[str]


def build_subject_search_context(subject: Subject) -> SubjectSearchContext:
    version = subject.current_version
    official_name = (version.official_name if version else "").strip()
    profile = SubjectBusinessProfile.objects.filter(subject=subject).first()
    brand_name = (profile.brand_name if profile else "").strip()

    anchors: list[str] = []
    for value in (official_name, brand_name):
        append_unique(anchors, value)
    if version is not None:
        name_values = SubjectName.objects.filter(
            subject_version=version
        ).values_list("display_value", flat=True)
        for value in name_values:
            append_unique(anchors, value)
    if not official_name and anchors:
        official_name = anchors[0]

    products: list[str] = []
    if version is not None:
        product_qs = SubjectProduct.objects.filter(
            subject_version=version
        ).order_by("-include_in_mention", "display_value")
        for value in product_qs.values_list("display_value", flat=True)[:8]:
            append_unique(products, value)

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
            append_unique(keywords, value)

    self_domains = extract_self_domains(version.field_values if version else {})
    return SubjectSearchContext(
        official_name=official_name,
        anchors=anchors,
        products=products,
        keywords=keywords,
        self_domains=self_domains,
    )


def primary_anchor(anchors: list[str], official: str) -> str:
    candidates = [
        value
        for value in anchors
        if 2 <= len(value) <= 24 and value != official
    ]
    if candidates:
        return min(candidates, key=len)
    return official


def append_query(queries: list[str], value: str) -> None:
    candidate = truncate_baidu_query(value)
    if not candidate:
        return
    key = candidate.casefold()
    if all(existing.casefold() != key for existing in queries):
        queries.append(candidate)


def append_unique(values: list[str], value: str) -> None:
    candidate = " ".join((value or "").split()).strip()
    if len(candidate) < 2:
        return
    key = candidate.casefold()
    if all(existing.casefold() != key for existing in values):
        values.append(candidate)


def extract_self_domains(field_values) -> set[str]:
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
