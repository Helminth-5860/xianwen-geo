from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.keywords.models import Keyword
from apps.questions.models import Question

from .models import WebsiteAudit, WebsiteAuditPage

_PUBLIC_FIELD_HINTS = (
    "name",
    "brand",
    "business",
    "product",
    "service",
    "description",
    "industry",
    "audience",
    "target",
    "region",
    "website",
    "official",
    "channel",
    "social",
)
_SENSITIVE_FIELD_HINTS = (
    "phone",
    "mobile",
    "contact",
    "address",
    "id_card",
    "identity",
    "password",
    "secret",
    "token",
    "credential",
)
_PAGE_INTENT_TERMS = (
    "/about",
    "/product",
    "/products",
    "/service",
    "/services",
    "/solution",
    "/solutions",
    "/case",
    "/cases",
    "/faq",
    "/news",
    "/blog",
    "/article",
    "/contact",
    "关于",
    "产品",
    "服务",
    "方案",
    "案例",
    "常见问题",
    "新闻",
    "文章",
    "联系",
)


@dataclass(frozen=True)
class SemanticAuditContext:
    subject: dict[str, Any]
    keywords: list[dict[str, Any]]
    questions: list[dict[str, Any]]
    pages: list[dict[str, Any]]
    allowed_urls: frozenset[str]
    allowed_question_ids: frozenset[str]
    page_text_by_url: dict[str, str]


def _safe_scalar(value: object, *, maximum: int = 1000) -> object | None:
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = " ".join(value.split())
        return text[:maximum] if text else None
    if isinstance(value, list):
        rows = []
        for item in value[:30]:
            safe = _safe_scalar(item, maximum=300)
            if safe not in (None, "", [], {}):
                rows.append(safe)
        return rows or None
    if isinstance(value, dict):
        output: dict[str, object] = {}
        for key, item in list(value.items())[:30]:
            normalized = str(key).strip().lower()
            if any(hint in normalized for hint in _SENSITIVE_FIELD_HINTS):
                continue
            safe = _safe_scalar(item, maximum=500)
            if safe not in (None, "", [], {}):
                output[str(key)[:100]] = safe
        return output or None
    return None


def _public_subject_fields(values: object) -> dict[str, object]:
    if not isinstance(values, dict):
        return {}
    output: dict[str, object] = {}
    for raw_key, raw_value in values.items():
        key = str(raw_key).strip()
        normalized = key.lower()
        if not key or any(hint in normalized for hint in _SENSITIVE_FIELD_HINTS):
            continue
        if not any(hint in normalized for hint in _PUBLIC_FIELD_HINTS):
            continue
        safe = _safe_scalar(raw_value)
        if safe not in (None, "", [], {}):
            output[key[:100]] = safe
    return output


def _subject_payload(audit: WebsiteAudit) -> dict[str, Any]:
    subject = audit.subject
    version = subject.current_version
    payload: dict[str, Any] = {
        "subject_id": str(subject.id),
        "official_name": version.official_name if version else "",
        "aliases": [],
        "products": [],
        "public_fields": _public_subject_fields(version.field_values if version else {}),
    }
    if version is not None:
        payload["aliases"] = list(
            version.names.exclude(role="official_name").values_list("display_value", flat=True)[:20]
        )
        payload["products"] = list(
            version.products.values_list("display_value", flat=True)[:30]
        )
    profile = getattr(subject, "business_profile", None)
    if profile is not None:
        payload["brand_name"] = profile.brand_name
        payload["primary_business"] = profile.primary_business[:3000]
        safe_social = _safe_scalar(profile.social_channels, maximum=500)
        if safe_social:
            payload["social_channels"] = safe_social
    return payload


def _keyword_payload(audit: WebsiteAudit, maximum: int) -> list[dict[str, Any]]:
    keyword_set = getattr(audit.subject, "keyword_set", None)
    version = getattr(keyword_set, "current_version", None)
    if version is None:
        return []
    rows = Keyword.objects.filter(keyword_set_version=version).order_by(
        "sort_order", "id"
    )[:maximum]
    return [
        {
            "id": str(row.id),
            "text": row.text,
            "priority": row.priority,
            "business_category": row.business_category,
            "search_intent": row.search_intent,
            "region": row.region_text if row.is_regional else "",
        }
        for row in rows
    ]


def _question_payload(audit: WebsiteAudit, maximum: int) -> list[dict[str, Any]]:
    workspace = getattr(audit.subject, "question_bank_workspace", None)
    version = getattr(workspace, "current_version", None)
    if version is None:
        return []
    rows = Question.objects.filter(
        question_bank_version=version,
        participates_in_scoring=True,
    ).order_by("sort_order", "id")[:maximum]
    return [
        {
            "id": str(row.id),
            "text": row.text,
            "priority": row.priority,
            "question_type": row.question_type,
            "category": row.primary_category_name,
        }
        for row in rows
    ]


def _page_priority(page: WebsiteAuditPage) -> tuple[int, int, int, int, str]:
    haystack = f"{page.url} {page.title}".lower()
    intent_rank = 0 if any(term.lower() in haystack for term in _PAGE_INTENT_TERMS) else 1
    root_rank = 0 if page.source == WebsiteAuditPage.Source.ROOT else 1
    return (
        root_rank,
        intent_rank,
        page.depth,
        -page.internal_links_count,
        page.url,
    )


def _page_payload(
    audit: WebsiteAudit,
    *,
    maximum_pages: int,
    max_chars_per_page: int,
    max_total_chars: int,
) -> list[dict[str, Any]]:
    candidates = list(
        audit.pages.filter(http_status=200, fetch_error="")
        .exclude(text_sample="")
        .order_by("depth", "url")
    )
    candidates.sort(key=_page_priority)
    selected: list[dict[str, Any]] = []
    used = 0
    for page in candidates:
        if len(selected) >= maximum_pages or used >= max_total_chars:
            break
        remaining = max_total_chars - used
        text = page.text_sample[: min(max_chars_per_page, remaining)]
        if not text.strip():
            continue
        selected.append(
            {
                "page_id": str(page.id),
                "url": page.final_url or page.url,
                "title": page.title,
                "meta_description": page.meta_description[:1000],
                "headings": page.headings,
                "schema_types": page.schema_types,
                "text": text,
                "text_characters": page.text_characters,
                "internal_links": page.internal_links_count,
                "external_links": page.external_links_count,
            }
        )
        used += len(text)
    return selected


def build_semantic_audit_context(
    audit: WebsiteAudit,
    *,
    maximum_pages: int,
    max_chars_per_page: int,
    max_total_chars: int,
    maximum_keywords: int,
    maximum_questions: int,
) -> SemanticAuditContext:
    pages = _page_payload(
        audit,
        maximum_pages=maximum_pages,
        max_chars_per_page=max_chars_per_page,
        max_total_chars=max_total_chars,
    )
    questions = _question_payload(audit, maximum_questions)
    return SemanticAuditContext(
        subject=_subject_payload(audit),
        keywords=_keyword_payload(audit, maximum_keywords),
        questions=questions,
        pages=pages,
        allowed_urls=frozenset(str(row["url"]) for row in pages),
        allowed_question_ids=frozenset(str(row["id"]) for row in questions),
        page_text_by_url={str(row["url"]): str(row["text"]) for row in pages},
    )
