from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from django.utils import timezone

from .models import NegativeEvent
from .scoring import event_risk

CLAIM_PRIORITY = {
    NegativeEvent.ClaimType.OFFICIAL_FINDING: 7,
    NegativeEvent.ClaimType.REPORTED_FACT: 6,
    NegativeEvent.ClaimType.REPORTED_CLAIM: 5,
    NegativeEvent.ClaimType.USER_ALLEGATION: 4,
    NegativeEvent.ClaimType.OPINION: 3,
    NegativeEvent.ClaimType.RUMOR: 2,
    NegativeEvent.ClaimType.REBUTTAL: 1,
}


@dataclass
class EventCluster:
    key: str
    items: list[dict]


def _text(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", (value or "").casefold())[:500]


def _trigrams(value: str) -> set[str]:
    normalized = _text(value)
    if len(normalized) < 3:
        return {normalized} if normalized else set()
    return {normalized[index : index + 3] for index in range(len(normalized) - 2)}


def title_similarity(left: str, right: str) -> float:
    left_normalized = _text(left)
    right_normalized = _text(right)
    if not left_normalized or not right_normalized:
        return 0.0
    sequence = SequenceMatcher(None, left_normalized, right_normalized).ratio()
    left_trigrams = _trigrams(left_normalized)
    right_trigrams = _trigrams(right_normalized)
    jaccard = len(left_trigrams & right_trigrams) / max(1, len(left_trigrams | right_trigrams))
    return max(sequence, jaccard)


def _date_compatible(left, right) -> bool:
    if left is None or right is None:
        return True
    return abs((left - right).days) <= 45


def cluster_items(items: list[dict]) -> list[EventCluster]:
    clusters: list[EventCluster] = []
    ordered_items = sorted(
        items,
        key=lambda row: (
            row.get("published_at") or timezone.now(),
            -row["severity_score"],
        ),
    )
    for item in ordered_items:
        matched = None
        for cluster in clusters:
            head = cluster.items[0]
            if item["category"] != head["category"]:
                continue
            if not _date_compatible(item.get("published_at"), head.get("published_at")):
                continue
            similarity = max(
                title_similarity(item.get("event_title", ""), head.get("event_title", "")),
                title_similarity(item.get("title", ""), head.get("title", "")),
            )
            if similarity >= 0.58:
                matched = cluster
                break
        if matched is None:
            published_at = item.get("published_at")
            published_key = published_at.date().isoformat() if published_at else "unknown"
            raw_key = (
                f"{item['category']}|"
                f"{_text(str(item.get('event_title') or item.get('title') or ''))}|"
                f"{published_key}"
            )
            matched = EventCluster(
                key=hashlib.sha1(raw_key.encode("utf-8")).hexdigest(),
                items=[],
            )
            clusters.append(matched)
        matched.items.append(item)
    return clusters


def _event_status(items: list[dict]) -> str:
    statuses = {row["event_status"] for row in items}
    if NegativeEvent.Status.CONFIRMED in statuses:
        return NegativeEvent.Status.CONFIRMED
    if statuses == {NegativeEvent.Status.RETRACTED}:
        return NegativeEvent.Status.RETRACTED
    if statuses == {NegativeEvent.Status.FALSE_POSITIVE}:
        return NegativeEvent.Status.FALSE_POSITIVE
    if NegativeEvent.Status.RESOLVED in statuses:
        return NegativeEvent.Status.RESOLVED
    if NegativeEvent.Status.DISPUTED in statuses:
        return NegativeEvent.Status.DISPUTED
    if NegativeEvent.Status.REPORTED in statuses:
        return NegativeEvent.Status.REPORTED
    return NegativeEvent.Status.SUSPECTED


def build_event(cluster: EventCluster) -> dict:
    items = cluster.items
    severity_representative = max(
        items,
        key=lambda row: (
            row["severity_score"],
            row["evidence_confidence"],
            row["authority_score"],
        ),
    )
    evidence_representative = max(
        items,
        key=lambda row: (
            row["evidence_confidence"],
            row["authority_score"],
            CLAIM_PRIORITY.get(row["claim_type"], 0),
        ),
    )
    domains = {row["root_domain"] for row in items if row.get("root_domain")}
    severity = max(row["severity_score"] for row in items)
    evidence = max(row["evidence_confidence"] for row in items)
    if len(domains) >= 2:
        evidence = min(100, evidence + min(18, (len(domains) - 1) * 6))
    visibility = max(row["visibility_score"] for row in items)
    freshness = max(row["freshness_score"] for row in items)
    status = _event_status(items)
    dates = [row["published_at"] for row in items if row.get("published_at")]
    first_seen = min(dates) if dates else None
    last_seen = max(dates) if dates else None
    risk = event_risk(
        severity=severity,
        evidence=evidence,
        visibility=visibility,
        freshness=freshness,
        status=status,
    )
    return {
        "cluster_key": cluster.key,
        "category": severity_representative["category"],
        "claim_type": evidence_representative["claim_type"],
        "status": status,
        "title": (
            severity_representative.get("event_title")
            or severity_representative.get("title")
            or "负面风险事件"
        )[:500],
        "summary": evidence_representative.get("ai_summary", "")[:4000],
        "severity_score": severity,
        "evidence_score": evidence,
        "visibility_score": visibility,
        "freshness_score": freshness,
        "current_risk": risk,
        "source_count": len(items),
        "independent_domain_count": len(domains),
        "first_seen_at": first_seen,
        "last_seen_at": last_seen,
        "items": items,
    }
