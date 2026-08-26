from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from math import ceil
from typing import Any, Iterable

from .models import WebsiteAuditFinding

REPORT_SCORE_VERSION = "website-audit-score-v1"

_RESULT_SCORES = {
    "pass": {"critical": 100, "high": 100, "medium": 100, "low": 100, "info": 100},
    "info": {"critical": 100, "high": 100, "medium": 100, "low": 100, "info": 100},
    "warn": {"critical": 20, "high": 35, "medium": 55, "low": 75, "info": 90},
    "fail": {"critical": 0, "high": 15, "medium": 35, "low": 60, "info": 80},
}
_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
_RESULT_ORDER = {"fail": 0, "warn": 1, "info": 2, "pass": 3}


@dataclass(frozen=True)
class RuleScore:
    score: int | None
    check_count: int
    pass_count: int
    warn_count: int
    fail_count: int
    critical_fail_count: int
    high_fail_count: int
    deductions: tuple[dict[str, Any], ...]


def _relation_rows(value: object) -> list[object]:
    if hasattr(value, "all"):
        return list(value.all())
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _finding_rule_score(result: str, severity: str) -> int:
    return _RESULT_SCORES.get(result, _RESULT_SCORES["warn"]).get(severity, 70)


def _deduplicate_findings(findings: Iterable[object]) -> list[object]:
    """Keep one worst result per check key so repeated page evidence cannot dominate a score."""
    selected: dict[str, object] = {}
    for finding in findings:
        key = str(getattr(finding, "check_key", "")).strip()
        if not key:
            continue
        current = selected.get(key)
        if current is None:
            selected[key] = finding
            continue
        candidate_rank = (
            _RESULT_ORDER.get(str(getattr(finding, "result", "warn")), 9),
            _SEVERITY_ORDER.get(str(getattr(finding, "severity", "info")), 9),
        )
        current_rank = (
            _RESULT_ORDER.get(str(getattr(current, "result", "warn")), 9),
            _SEVERITY_ORDER.get(str(getattr(current, "severity", "info")), 9),
        )
        if candidate_rank < current_rank:
            selected[key] = finding
    return list(selected.values())


def score_findings(findings: Iterable[object]) -> RuleScore:
    rows = _deduplicate_findings(findings)
    if not rows:
        return RuleScore(None, 0, 0, 0, 0, 0, 0, ())

    scores: list[int] = []
    results = Counter()
    critical_fail = 0
    high_fail = 0
    deductions: list[dict[str, Any]] = []
    for row in rows:
        result = str(getattr(row, "result", "warn"))
        severity = str(getattr(row, "severity", "info"))
        score = _finding_rule_score(result, severity)
        scores.append(score)
        results[result] += 1
        if result == "fail" and severity == "critical":
            critical_fail += 1
        if result == "fail" and severity == "high":
            high_fail += 1
        if result in {"fail", "warn"}:
            deductions.append(
                {
                    "check_key": str(getattr(row, "check_key", "")),
                    "title": str(getattr(row, "title", ""))[:300],
                    "severity": severity,
                    "result": result,
                    "rule_score": score,
                    "lost_points": 100 - score,
                    "affected_count": int(getattr(row, "affected_count", 0) or 0),
                }
            )

    score = round(sum(scores) / len(scores))
    # Many easy passes must not hide a blocker that prevents reliable crawling/indexing.
    if critical_fail:
        score = min(score, 49)
    elif high_fail:
        score = min(score, 79 if high_fail == 1 else 69)

    deductions.sort(
        key=lambda item: (
            _RESULT_ORDER.get(str(item["result"]), 9),
            _SEVERITY_ORDER.get(str(item["severity"]), 9),
            -int(item["lost_points"]),
            str(item["check_key"]),
        )
    )
    return RuleScore(
        score=score,
        check_count=len(rows),
        pass_count=results["pass"],
        warn_count=results["warn"],
        fail_count=results["fail"],
        critical_fail_count=critical_fail,
        high_fail_count=high_fail,
        deductions=tuple(deductions[:30]),
    )


def _weighted_score(values: dict[str, int], weights: dict[str, float]) -> int | None:
    available = [(key, weight) for key, weight in weights.items() if key in values]
    if not available:
        return None
    total_weight = sum(weight for _, weight in available)
    return round(sum(values[key] * weight for key, weight in available) / total_weight)


def _semantic_dimensions(audit: object) -> tuple[dict[str, int], int | None, int | None]:
    if str(getattr(audit, "semantic_status", "")) != "succeeded":
        return {}, None, None
    raw = getattr(audit, "semantic_scores", {}) or {}
    scores = {
        key: int(value)
        for key, value in raw.items()
        if key
        in {
            "entity_clarity",
            "fact_density",
            "citation_readiness",
            "topic_coverage",
            "credibility",
            "answer_readiness",
        }
        and type(value) is int
        and 0 <= value <= 100
    }
    ai_readability = _weighted_score(
        scores,
        {"entity_clarity": 0.40, "citation_readiness": 0.35, "credibility": 0.25},
    )
    content_readiness = _weighted_score(
        scores,
        {"fact_density": 0.30, "topic_coverage": 0.30, "answer_readiness": 0.40},
    )
    return scores, ai_readability, content_readiness


def _component_payload(name: str, rule_score: RuleScore) -> dict[str, Any]:
    return {
        "key": name,
        "score": rule_score.score,
        "check_count": rule_score.check_count,
        "pass_count": rule_score.pass_count,
        "warn_count": rule_score.warn_count,
        "fail_count": rule_score.fail_count,
        "critical_fail_count": rule_score.critical_fail_count,
        "high_fail_count": rule_score.high_fail_count,
        "deductions": list(rule_score.deductions),
    }


def _browser_metrics(snapshots: list[object]) -> dict[str, Any]:
    by_profile: dict[str, list[object]] = defaultdict(list)
    for row in snapshots:
        if str(getattr(row, "status", "")) == "succeeded":
            by_profile[str(getattr(row, "profile", "unknown"))].append(row)

    def percentile(values: list[float], pct: float) -> int | float | None:
        if not values:
            return None
        ordered = sorted(values)
        index = min(len(ordered) - 1, max(0, ceil(len(ordered) * pct) - 1))
        value = ordered[index]
        return round(value, 3) if not value.is_integer() else round(value)

    output: dict[str, Any] = {}
    for profile, rows in sorted(by_profile.items()):
        lcp = [float(value) for row in rows if (value := getattr(row, "lcp_ms", None)) is not None]
        cls = [float(value) for row in rows if (value := getattr(row, "cls", None)) is not None]
        tbt = [float(value) for row in rows if (value := getattr(row, "tbt_ms", None)) is not None]
        ttfb = [float(value) for row in rows if (value := getattr(row, "ttfb_ms", None)) is not None]
        output[profile] = {
            "sample_count": len(rows),
            "ttfb_p75_ms": percentile(ttfb, 0.75),
            "lcp_p75_ms": percentile(lcp, 0.75),
            "cls_p75": percentile(cls, 0.75),
            "tbt_p75_ms": percentile(tbt, 0.75),
            "failed_requests": sum(int(getattr(row, "failed_request_count", 0) or 0) for row in rows),
            "transfer_bytes": sum(int(getattr(row, "transfer_bytes", 0) or 0) for row in rows),
        }
    return output


def _semantic_summary(audit: object) -> dict[str, Any]:
    result = getattr(audit, "semantic_result", {}) or {}
    questions = result.get("question_assessments", []) if isinstance(result, dict) else []
    if not isinstance(questions, list):
        questions = []
    statuses = Counter(
        str(row.get("status")) for row in questions if isinstance(row, dict) and row.get("status")
    )
    topic_gaps = result.get("topic_gaps", []) if isinstance(result, dict) else []
    passages = result.get("citeable_passages", []) if isinstance(result, dict) else []
    findings = result.get("content_findings", []) if isinstance(result, dict) else []
    return {
        "question_coverage": {
            "total": len(questions),
            "answered": statuses["answered"],
            "partial": statuses["partial"],
            "missing": statuses["missing"],
        },
        "content_finding_count": len(findings) if isinstance(findings, list) else 0,
        "topic_gap_count": len(topic_gaps) if isinstance(topic_gaps, list) else 0,
        "citeable_passage_count": len(passages) if isinstance(passages, list) else 0,
        "summary": str(result.get("summary", ""))[:1200] if isinstance(result, dict) else "",
    }


def build_website_audit_report(audit: object) -> dict[str, Any]:
    findings = _relation_rows(getattr(audit, "findings", []))
    snapshots = _relation_rows(getattr(audit, "browser_snapshots", []))

    seo_rules = score_findings(
        row for row in findings if str(getattr(row, "category", "")) == WebsiteAuditFinding.Category.SEO
    )
    technical_rules = score_findings(
        row
        for row in findings
        if str(getattr(row, "category", "")) == WebsiteAuditFinding.Category.TECHNICAL
    )
    deterministic_geo = score_findings(
        row
        for row in findings
        if str(getattr(row, "category", "")) == WebsiteAuditFinding.Category.GEO
        and str(getattr(row, "method", "")) != WebsiteAuditFinding.Method.SEMANTIC
    )

    audit_status = str(getattr(audit, "status", ""))
    browser_status = str(getattr(audit, "browser_status", ""))
    semantic_status = str(getattr(audit, "semantic_status", ""))
    semantic_scores, ai_readability, content_readiness = _semantic_dimensions(audit)

    # A final GEO score requires both deterministic GEO checks and the semantic layer.
    geo_score = None
    if (
        semantic_status == "succeeded"
        and deterministic_geo.score is not None
        and ai_readability is not None
        and content_readiness is not None
    ):
        geo_score = _weighted_score(
            {
                "deterministic_geo": deterministic_geo.score,
                "ai_readability": ai_readability,
                "content_readiness": content_readiness,
            },
            {"deterministic_geo": 0.35, "ai_readability": 0.35, "content_readiness": 0.30},
        )

    # Do not publish a final overall score when browser evidence is absent or failed.
    overall_score = None
    if (
        audit_status == "succeeded"
        and browser_status in {"succeeded", "partial"}
        and semantic_status == "succeeded"
        and seo_rules.score is not None
        and technical_rules.score is not None
        and geo_score is not None
    ):
        overall_score = _weighted_score(
            {"seo": seo_rules.score, "geo": geo_score, "technical": technical_rules.score},
            {"seo": 0.25, "geo": 0.45, "technical": 0.30},
        )

    pending = (
        audit_status in {"queued", "running"}
        or browser_status in {"queued", "running"}
        or semantic_status in {"queued", "running"}
    )
    if pending:
        report_status = "pending"
    elif audit_status != "succeeded":
        report_status = "failed"
    elif semantic_status == "succeeded" and browser_status == "succeeded":
        report_status = "complete"
    else:
        report_status = "partial"

    missing_layers: list[str] = []
    if browser_status not in {"succeeded", "partial"}:
        missing_layers.append("browser")
    if semantic_status != "succeeded":
        missing_layers.append("semantic")

    issue_rows = [
        row for row in findings if str(getattr(row, "result", "")) in {"fail", "warn"}
    ]
    issue_rows.sort(
        key=lambda row: (
            _RESULT_ORDER.get(str(getattr(row, "result", "warn")), 9),
            _SEVERITY_ORDER.get(str(getattr(row, "severity", "info")), 9),
            str(getattr(row, "check_key", "")),
        )
    )
    top_issues = [
        {
            "check_key": str(getattr(row, "check_key", "")),
            "category": str(getattr(row, "category", "")),
            "dimension": str(getattr(row, "dimension", "")),
            "method": str(getattr(row, "method", "")),
            "severity": str(getattr(row, "severity", "")),
            "result": str(getattr(row, "result", "")),
            "title": str(getattr(row, "title", ""))[:300],
            "summary": str(getattr(row, "summary", ""))[:1200],
            "recommendation": str(getattr(row, "recommendation", ""))[:1200],
            "affected_count": int(getattr(row, "affected_count", 0) or 0),
        }
        for row in issue_rows[:20]
    ]

    issue_counts = Counter(
        (str(getattr(row, "category", "")), str(getattr(row, "severity", "")))
        for row in issue_rows
    )
    return {
        "score_version": REPORT_SCORE_VERSION,
        "status": report_status,
        "missing_layers": missing_layers,
        "overall_score": overall_score,
        "scores": {
            "seo": seo_rules.score,
            "geo": geo_score,
            "technical_health": technical_rules.score,
            "ai_readability": ai_readability,
            "content_readiness": content_readiness,
        },
        "semantic_dimensions": semantic_scores,
        "components": {
            "seo_rules": _component_payload("seo_rules", seo_rules),
            "geo_rules": _component_payload("geo_rules", deterministic_geo),
            "technical_rules": _component_payload("technical_rules", technical_rules),
            "geo_weights": {
                "deterministic_geo": 0.35,
                "ai_readability": 0.35,
                "content_readiness": 0.30,
            },
            "overall_weights": {"seo": 0.25, "geo": 0.45, "technical": 0.30},
        },
        "issue_counts": {
            category: {
                severity: issue_counts[(category, severity)]
                for severity in ("critical", "high", "medium", "low", "info")
                if issue_counts[(category, severity)]
            }
            for category in ("seo", "geo", "technical")
        },
        "top_issues": top_issues,
        "browser_metrics": _browser_metrics(snapshots),
        "semantic_summary": _semantic_summary(audit),
        "evidence": {
            "fetched_pages": int(getattr(audit, "fetched_count", 0) or 0),
            "failed_pages": int(getattr(audit, "failed_count", 0) or 0),
            "browser_completed": int(getattr(audit, "browser_completed_count", 0) or 0),
            "browser_failed": int(getattr(audit, "browser_failed_count", 0) or 0),
            "semantic_pages": int(getattr(audit, "semantic_page_count", 0) or 0),
            "semantic_questions": int(getattr(audit, "semantic_question_count", 0) or 0),
        },
    }
