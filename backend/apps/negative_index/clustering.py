from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from django.utils import timezone

from .scoring import event_risk


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
    return {normalized[index:index + 3] for index in range(len(normalized) - 2)}


def title_similarity(left: str, right: str) -> float:
    left_n, right_n = _text(left), _text(right)
    if not left_n or not right_n:
        return 0.0
    sequence = SequenceMatcher(None, left_n, right_n).ratio()
    lt, rt = _trigrams(left_n), _trigrams(right_n)
    jaccard = len(lt & rt) / max(1, len(lt | rt))
    return max(sequence, jaccard)


def _date_compatible(left, right) -> bool:
    if left is None or right is None:
        return True
    return abs((left - right).days) <= 45


def cluster_items(items: list[dict]) -> list[EventCluster]:
    clusters: list[EventCluster] = []
    for item in sorted(items, key=lambda row: (row.get("published_at") or timezone.now(), -row["severity_score"])):
        matched = None
        for cluster in clusters:
            head = cluster.items[0]
            if item["category"] != head["category"] or not _date_compatible(item.get("published_at"), head.get("published_at")):
                continue
            similarity = max(title_similarity(item.get("event_title", ""), head.get("event_title", "")), title_similarity(item.get("title", ""), head.get("title", "")))
            if similarity >= 0.58:
                matched = cluster
                break
        if matched is None:
            raw_key = f"{item['category']}|{_text(item.get('event_title') or item.get('title'))}|{item.get('published_at').date().isoformat() if item.get('published_at') else 'unknown'}"
            matched = EventCluster(key=hashlib.sha1(raw_key.encode("utf-8")).hexdigest(), items=[])
            clusters.append(matched)
        matched.items.append(item)
    return clusters


def build_event(cluster: EventCluster) -> dict:
    items = cluster.items
    representative = max(items, key=lambda row: (row["severity_score"], row["evidence_confidence"], row["authority_score"]))
    source_count = len(items)
    domains = {row["root_domain"] for row in items if row.get("root_domain")}
    severity = max(row["severity_score"] for row in items)
    evidence = max(row["evidence_confidence"] for row in items)
    if len(domains) >= 2:
        evidence = min(100, evidence + min(18, (len(domains) - 1) * 6))
    visibility = max(row["visibility_score"] for row in items)
    freshness = max(row["freshness_score"] for row in items)
    statuses = {row["event_status"] for row in items}
    if "confirmed" in statuses:
        status = "confirmed"
    elif "retracted" in statuses and len(statuses) == 1:
        status = "retracted"
    elif "false_positive" in statuses and len(statuses) == 1:
        status = "false_positive"
    elif "resolved" in statuses:
        status = "resolved"
    elif "disputed" in statuses:
        status = "disputed"
    elif "reported" in statuses:
        status = "reported"
    else:
        status = "suspected"
    dates = [row["published_at"] for row in items if row.get("published_at")]
    first_seen = min(dates) if dates else None
    last_seen = max(dates) if dates else None
    risk = event_risk(severity=severity, evidence=evidence, visibility=visibility, freshness=freshness, status=status)
    return {
        "cluster_key": cluster.key,
        "category": representative["category"],
        "claim_type": representative["claim_type"],
        "status": status,
        "title": (representative.get("event_title") or representative.get("title") or "负面风险事件")[:500],
        "summary": representative.get("ai_summary", "")[:4000],
        "severity_score": severity,
        "evidence_score": evidence,
        "visibility_score": visibility,
        "freshness_score": freshness,
        "current_risk": risk,
        "source_count": source_count,
        "independent_domain_count": len(domains),
        "first_seen_at": first_seen,
        "last_seen_at": last_seen,
        "items": items,
    }
