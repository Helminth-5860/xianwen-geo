from __future__ import annotations

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone


STATUS_MULTIPLIERS = {
    "confirmed": 1.00,
    "reported": 0.90,
    "disputed": 0.65,
    "suspected": 0.55,
    "resolved": 0.35,
    "retracted": 0.0,
    "false_positive": 0.0,
}


def event_risk(*, severity: int, evidence: int, visibility: int, freshness: int, status: str) -> Decimal:
    if status in {"retracted", "false_positive"}:
        return Decimal("0.00")
    evidence_factor = 0.25 + 0.75 * (max(0, min(100, evidence)) / 100)
    visibility_factor = 0.70 + 0.30 * (max(0, min(100, visibility)) / 100)
    freshness_factor = 0.55 + 0.45 * (max(0, min(100, freshness)) / 100)
    status_factor = STATUS_MULTIPLIERS.get(status, 0.55)
    value = max(0, min(100, severity)) * evidence_factor * visibility_factor * freshness_factor * status_factor
    return Decimal(str(min(100.0, value))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_negative_index(events: list[dict]) -> tuple[Decimal, dict[str, float]]:
    active = sorted((event for event in events if float(event["current_risk"]) > 0), key=lambda item: float(item["current_risk"]), reverse=True)[:10]
    if not active:
        return Decimal("0.00"), {"max_event_risk": 0.0, "average_evidence": 0.0, "average_visibility": 0.0, "recent_pressure": 0.0, "event_count_factor": 0.0}
    weights = (0.85, 0.50, 0.36, 0.28, 0.22, 0.18, 0.15, 0.13, 0.11, 0.10)
    remaining = 1.0
    for event, weight in zip(active, weights, strict=False):
        probability = min(0.99, float(event["current_risk"]) / 100.0 * weight)
        remaining *= 1.0 - probability
    index = min(100.0, (1.0 - remaining) * 100.0)
    recent_cutoff = timezone.now() - timedelta(days=30)
    recent = [event for event in active if event.get("last_seen_at") and event["last_seen_at"] >= recent_cutoff]
    recent_pressure = sum(float(event["current_risk"]) for event in recent) / max(1, len(recent))
    factors = {
        "max_event_risk": round(max(float(event["current_risk"]) for event in active), 2),
        "average_evidence": round(sum(event["evidence_score"] for event in active) / len(active), 2),
        "average_visibility": round(sum(event["visibility_score"] for event in active) / len(active), 2),
        "recent_pressure": round(recent_pressure, 2),
        "event_count_factor": round(min(100.0, len(active) / 10 * 100), 2),
    }
    return Decimal(str(index)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), factors


def risk_level(score: float | Decimal | None) -> str:
    value = float(score or 0)
    if value >= 71:
        return "high"
    if value >= 41:
        return "elevated"
    if value >= 16:
        return "watch"
    return "low"
