from __future__ import annotations

import time as time_module
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import NotFound as DRFNotFound

from apps.search_discovery.provider import BaiduSearchProvider, SearchProviderError
from apps.search_discovery.source_quality import (
    classify_source,
    freshness_score,
    relevance_score,
    visibility_score,
)
from apps.subjects.subject_services import subject_for_user_or_404

from .classifier import (
    CandidateAnalysis,
    NegativeClassifierError,
    analyze_candidates,
    fallback_analysis,
    rule_signal,
    should_verify,
)
from .clustering import build_event, cluster_items
from .models import (
    NegativeEvent,
    NegativeIndexHit,
    NegativeIndexItem,
    NegativeIndexScan,
)
from .scanner import run_negative_search
from .scoring import calculate_negative_index
from .verifier import verify_candidate


class NegativeIndexNotFound(Exception):
    pass


class NegativeIndexBusy(Exception):
    pass


def recover_stale_negative_index_scans(*, user=None, subject_id=None) -> int:
    total_budget = int(getattr(settings, "NEGATIVE_INDEX_TOTAL_TIMEOUT_SECONDS", 300))
    cutoff = timezone.now() - timedelta(seconds=max(total_budget + 90, 390))
    queryset = NegativeIndexScan.objects.filter(
        status__in=(
            NegativeIndexScan.Status.QUEUED,
            NegativeIndexScan.Status.RUNNING,
        )
    )
    if user is not None:
        queryset = queryset.filter(user=user)
    if subject_id is not None:
        queryset = queryset.filter(subject_id=subject_id)
    return queryset.filter(
        Q(status=NegativeIndexScan.Status.QUEUED, created_at__lt=cutoff)
        | Q(status=NegativeIndexScan.Status.RUNNING, started_at__lt=cutoff)
        | Q(
            status=NegativeIndexScan.Status.RUNNING,
            started_at__isnull=True,
            created_at__lt=cutoff,
        )
    ).update(
        status=NegativeIndexScan.Status.FAILED,
        stage=NegativeIndexScan.Stage.COMPLETED,
        stable_error_code="NEGATIVE_INDEX_TIMEOUT",
        finished_at=timezone.now(),
        updated_at=timezone.now(),
    )


def create_negative_index_scan(*, user, subject_id) -> NegativeIndexScan:
    try:
        subject = subject_for_user_or_404(user=user, subject_id=subject_id)
    except DRFNotFound as exc:
        raise NegativeIndexNotFound from exc
    recover_stale_negative_index_scans(subject_id=subject.pk)
    if NegativeIndexScan.objects.filter(
        subject=subject,
        status__in=(
            NegativeIndexScan.Status.QUEUED,
            NegativeIndexScan.Status.RUNNING,
        ),
    ).exists():
        raise NegativeIndexBusy
    try:
        return NegativeIndexScan.objects.create(
            user=user,
            subject=subject,
            ai_provider=getattr(
                settings,
                "NEGATIVE_INDEX_AI_PROVIDER",
                "deepseek",
            )[:32],
        )
    except IntegrityError as exc:
        raise NegativeIndexBusy from exc


def _start_scan(scan_id) -> NegativeIndexScan:
    with transaction.atomic():
        try:
            # Lock only the scan row. Subject.current_version is nullable; joining it
            # under SELECT ... FOR UPDATE causes PostgreSQL to reject the nullable side
            # of the outer join. The version is loaded lazily after the lock boundary.
            scan = (
                NegativeIndexScan.objects.select_for_update()
                .select_related("subject")
                .get(pk=scan_id)
            )
        except NegativeIndexScan.DoesNotExist as exc:
            raise NegativeIndexNotFound from exc
        if scan.status in {
            NegativeIndexScan.Status.SUCCEEDED,
            NegativeIndexScan.Status.PARTIAL,
            NegativeIndexScan.Status.LIMIT_REACHED,
        }:
            return scan
        if scan.status not in {
            NegativeIndexScan.Status.QUEUED,
            NegativeIndexScan.Status.FAILED,
        }:
            raise NegativeIndexBusy
        scan.status = NegativeIndexScan.Status.RUNNING
        scan.stage = NegativeIndexScan.Stage.PREPARING
        scan.started_at = timezone.now()
        scan.finished_at = None
        scan.stable_error_code = ""
        scan.save(
            update_fields=(
                "status",
                "stage",
                "started_at",
                "finished_at",
                "stable_error_code",
                "updated_at",
            )
        )
        return scan


def fail_negative_index_scan(
    scan_id,
    stable_error_code: str = "NEGATIVE_INDEX_FAILED",
) -> None:
    NegativeIndexScan.objects.filter(pk=scan_id).update(
        status=NegativeIndexScan.Status.FAILED,
        stage=NegativeIndexScan.Stage.COMPLETED,
        stable_error_code=stable_error_code[:100],
        finished_at=timezone.now(),
        updated_at=timezone.now(),
    )


def _apply_analysis(
    candidate: dict,
    analysis: CandidateAnalysis,
    source: str,
) -> None:
    candidate.update(
        {
            "subject_relevance_ai": analysis.subject_relevance,
            "negative_confidence": analysis.negative_confidence,
            "category": analysis.category,
            "severity_score": analysis.severity,
            "claim_type": analysis.claim_type,
            "evidence_confidence": analysis.evidence_confidence,
            "event_status": analysis.event_status,
            "event_title": analysis.event_title,
            "ai_summary": analysis.summary,
            "classification_source": source,
        }
    )


def _analysis_from_candidate(candidate: dict) -> CandidateAnalysis:
    return CandidateAnalysis(
        subject_relevance=int(candidate.get("subject_relevance_ai", 0)),
        negative_confidence=int(candidate["negative_confidence"]),
        category=str(candidate["category"]),
        severity=int(candidate["severity_score"]),
        claim_type=str(candidate["claim_type"]),
        evidence_confidence=int(candidate["evidence_confidence"]),
        event_status=str(candidate["event_status"]),
        event_title=str(candidate["event_title"]),
        summary=str(candidate.get("ai_summary", "")),
    )


def _fallback_candidate(candidate: dict) -> CandidateAnalysis:
    return fallback_analysis(
        title=candidate["title"],
        snippet=candidate["snippet"],
        source_type=candidate["source_type"],
        authority=candidate["authority_score"],
        signal=candidate["rule_signal"],
    )


def _build_candidates(payload) -> list[dict]:
    minimum_relevance = int(getattr(settings, "NEGATIVE_INDEX_MIN_RELEVANCE_SCORE", 60))
    minimum_rule_signal = int(getattr(settings, "NEGATIVE_INDEX_MIN_RULE_SIGNAL_SCORE", 25))
    candidates: list[dict] = []
    for record in payload.records.values():
        matched_queries = set(record["matched_queries"])
        relevance = relevance_score(
            title=record["title"],
            snippet=record["snippet"],
            website=record["website"],
            anchors=payload.context.anchors,
            official_name=payload.context.official_name,
            matched_queries=matched_queries,
        )
        if relevance < minimum_relevance:
            continue
        source_type, authority = classify_source(
            root=record["root_domain"],
            domain=record["domain"],
            website=record["website"],
            title=record["title"],
            self_domains=payload.context.self_domains,
        )
        signal = rule_signal(record["title"], record["snippet"])
        if signal.score < minimum_rule_signal and source_type != "government_association":
            continue
        candidates.append(
            {
                **record,
                "source_type": source_type,
                "authority_score": authority,
                "relevance_score": relevance,
                "visibility_score": visibility_score(record["best_rank"]),
                "freshness_score": freshness_score(record["published_at"]),
                "matched_query_count": len(matched_queries),
                "rule_signal_score": signal.score,
                "rule_signal": signal,
            }
        )

    candidates.sort(
        key=lambda row: (
            row["rule_signal_score"],
            row["authority_score"],
            row["relevance_score"],
            -row["best_rank"],
        ),
        reverse=True,
    )
    maximum = int(getattr(settings, "NEGATIVE_INDEX_MAX_AI_CANDIDATES", 20))
    candidates = candidates[:maximum]
    for index, candidate in enumerate(candidates, start=1):
        candidate["candidate_id"] = f"c{index}"
        candidate["verification_status"] = NegativeIndexItem.VerificationStatus.NOT_REQUESTED
        candidate["verification_excerpt"] = ""
        candidate["verification_error_code"] = ""
    return candidates


def _classify_candidates(candidates: list[dict], context) -> tuple[bool, dict[str, str]]:
    degraded = False
    ai_metadata = {
        "provider": getattr(settings, "NEGATIVE_INDEX_AI_PROVIDER", "deepseek"),
        "model_key": "",
        "provider_model_id": "",
    }
    batch_size = int(getattr(settings, "NEGATIVE_INDEX_AI_BATCH_SIZE", 10))
    ai_failed = False
    for offset in range(0, len(candidates), batch_size):
        batch = candidates[offset : offset + batch_size]
        if ai_failed:
            for candidate in batch:
                _apply_analysis(
                    candidate,
                    _fallback_candidate(candidate),
                    NegativeIndexItem.ClassificationSource.RULE,
                )
            continue
        try:
            result = analyze_candidates(batch, context)
            ai_metadata = {
                "provider": result.provider_key,
                "model_key": result.model_key,
                "provider_model_id": result.provider_model_id,
            }
            for candidate in batch:
                _apply_analysis(
                    candidate,
                    result.analyses[candidate["candidate_id"]],
                    NegativeIndexItem.ClassificationSource.AI,
                )
        except NegativeClassifierError:
            degraded = True
            ai_failed = True
            for candidate in batch:
                _apply_analysis(
                    candidate,
                    _fallback_candidate(candidate),
                    NegativeIndexItem.ClassificationSource.RULE,
                )
    return degraded, ai_metadata


def _verify_candidates(
    candidates: list[dict],
    context,
    ai_metadata: dict[str, str],
) -> tuple[bool, int, dict[str, str]]:
    verification_candidates = [
        candidate
        for candidate in candidates
        if should_verify(
            _analysis_from_candidate(candidate),
            authority=candidate["authority_score"],
        )
    ]
    verification_candidates.sort(
        key=lambda row: (
            row["severity_score"],
            100 - row["evidence_confidence"],
            row["authority_score"],
        ),
        reverse=True,
    )
    maximum = int(getattr(settings, "NEGATIVE_INDEX_MAX_VERIFICATIONS", 2))
    verification_candidates = verification_candidates[:maximum]

    degraded = False
    verified_count = 0
    for candidate in verification_candidates:
        verification = verify_candidate(candidate, context)
        if not verification.succeeded:
            candidate["verification_status"] = NegativeIndexItem.VerificationStatus.FAILED
            candidate["verification_error_code"] = verification.error_code
            degraded = True
            continue
        verified_count += 1
        candidate["verification_status"] = NegativeIndexItem.VerificationStatus.SUCCEEDED
        candidate["verification_excerpt"] = verification.excerpt
        try:
            result = analyze_candidates([candidate], context)
            _apply_analysis(
                candidate,
                result.analyses[candidate["candidate_id"]],
                NegativeIndexItem.ClassificationSource.VERIFIED_AI,
            )
            ai_metadata = {
                "provider": result.provider_key,
                "model_key": result.model_key,
                "provider_model_id": result.provider_model_id,
            }
        except NegativeClassifierError:
            degraded = True
    return degraded, verified_count, ai_metadata


def _negative_items(candidates: list[dict]) -> list[dict]:
    minimum_negative = int(getattr(settings, "NEGATIVE_INDEX_MIN_NEGATIVE_CONFIDENCE", 60))
    return [
        candidate
        for candidate in candidates
        if candidate["negative_confidence"] >= minimum_negative
        and candidate.get("subject_relevance_ai", 0) >= 60
        and candidate["claim_type"] != NegativeEvent.ClaimType.REBUTTAL
        and candidate["event_status"]
        not in {
            NegativeEvent.Status.RETRACTED,
            NegativeEvent.Status.FALSE_POSITIVE,
        }
    ]


def _event_payloads(negative_items: list[dict]) -> list[dict]:
    events: list[dict] = []
    for cluster in cluster_items(negative_items):
        event = build_event(cluster)
        for item in event["items"]:
            item["cluster_key"] = event["cluster_key"]
        events.append(event)
    return events


def _event_objects(scan: NegativeIndexScan, events: list[dict]):
    objects: list[NegativeEvent] = []
    by_cluster: dict[str, NegativeEvent] = {}
    for event in events:
        obj = NegativeEvent(
            scan=scan,
            category=event["category"],
            claim_type=event["claim_type"],
            status=event["status"],
            title=event["title"],
            summary=event["summary"],
            severity_score=event["severity_score"],
            evidence_score=event["evidence_score"],
            visibility_score=event["visibility_score"],
            freshness_score=event["freshness_score"],
            current_risk=event["current_risk"],
            source_count=event["source_count"],
            independent_domain_count=event["independent_domain_count"],
            first_seen_at=event["first_seen_at"],
            last_seen_at=event["last_seen_at"],
            cluster_key=event["cluster_key"],
        )
        objects.append(obj)
        by_cluster[event["cluster_key"]] = obj
    return objects, by_cluster


def _item_objects(
    scan: NegativeIndexScan,
    negative_items: list[dict],
    event_by_cluster: dict[str, NegativeEvent],
):
    objects: list[NegativeIndexItem] = []
    by_url: dict[str, NegativeIndexItem] = {}
    for item in negative_items:
        obj = NegativeIndexItem(
            scan=scan,
            event=event_by_cluster[item["cluster_key"]],
            original_url=item["original_url"],
            normalized_url=item["normalized_url"],
            domain=item["domain"],
            root_domain=item["root_domain"],
            website=item["website"],
            title=item["title"],
            snippet=item["snippet"],
            published_at=item["published_at"],
            source_type=item["source_type"],
            authority_score=item["authority_score"],
            relevance_score=item["relevance_score"],
            visibility_score=item["visibility_score"],
            freshness_score=item["freshness_score"],
            best_rank=item["best_rank"],
            matched_query_count=item["matched_query_count"],
            rule_signal_score=item["rule_signal_score"],
            negative_confidence=item["negative_confidence"],
            severity_score=item["severity_score"],
            evidence_confidence=item["evidence_confidence"],
            category=item["category"],
            claim_type=item["claim_type"],
            event_status=item["event_status"],
            event_title=item["event_title"],
            ai_summary=item["ai_summary"],
            classification_source=item["classification_source"],
            verification_status=item["verification_status"],
            verification_excerpt=item["verification_excerpt"],
            verification_error_code=item["verification_error_code"],
        )
        objects.append(obj)
        by_url[item["normalized_url"]] = obj
    return objects, by_url


def _persist_result(
    *,
    scan: NegativeIndexScan,
    payload,
    candidates: list[dict],
    negative_items: list[dict],
    events: list[dict],
    verified_count: int,
    ai_metadata: dict[str, str],
    final_status: str,
    started: float,
) -> dict:
    index_score, factor_scores = calculate_negative_index(events)
    high_risk_count = sum(1 for event in events if float(event["current_risk"]) >= 60)
    recent_cutoff = timezone.now() - timedelta(days=30)
    recent_count = sum(
        1 for event in events if event["last_seen_at"] and event["last_seen_at"] >= recent_cutoff
    )
    event_objects, event_by_cluster = _event_objects(scan, events)
    item_objects, item_by_url = _item_objects(
        scan,
        negative_items,
        event_by_cluster,
    )

    with transaction.atomic():
        locked = NegativeIndexScan.objects.select_for_update().get(pk=scan.pk)
        if locked.events.exists() or locked.items.exists() or locked.hits.exists():
            return {"scan_id": str(locked.id), "status": locked.status}

        if event_objects:
            NegativeEvent.objects.bulk_create(event_objects, batch_size=500)
        if item_objects:
            NegativeIndexItem.objects.bulk_create(item_objects, batch_size=1000)

        hit_objects: list[NegativeIndexHit] = []
        for hit in payload.hits:
            item_obj = item_by_url.get(hit["normalized_url"])
            if item_obj is None:
                continue
            hit_objects.append(
                NegativeIndexHit(
                    scan=locked,
                    item=item_obj,
                    query=hit["query"],
                    rank=hit["rank"],
                    range_start=hit["range_start"],
                    range_end=hit["range_end"],
                )
            )
        if hit_objects:
            NegativeIndexHit.objects.bulk_create(
                hit_objects,
                batch_size=2000,
                ignore_conflicts=True,
            )

        locked.status = final_status
        locked.stage = NegativeIndexScan.Stage.COMPLETED
        locked.provider_request_count = payload.provider_requests
        locked.provider_error_count = payload.provider_errors
        locked.raw_result_count = payload.raw_results
        locked.unique_result_count = len(payload.records)
        locked.query_count = payload.query_count
        locked.candidate_count = len(candidates)
        locked.negative_item_count = len(negative_items)
        locked.event_count = len(events)
        locked.high_risk_event_count = high_risk_count
        locked.recent_30d_event_count = recent_count
        locked.verified_item_count = verified_count
        locked.index_score = index_score
        locked.factor_scores = factor_scores
        locked.progress = {
            "raw": payload.raw_results,
            "unique": len(payload.records),
            "candidates": len(candidates),
            "negative_items": len(negative_items),
            "events": len(events),
            "verified": verified_count,
        }
        locked.formula_version = "negative-index-v1"
        locked.classifier_version = "negative-classifier-v1"
        locked.ai_provider = ai_metadata["provider"][:32]
        locked.ai_model_key = ai_metadata["model_key"][:100]
        locked.ai_provider_model_id = ai_metadata["provider_model_id"][:255]
        locked.stable_error_code = ""
        locked.elapsed_ms = int((time_module.monotonic() - started) * 1000)
        locked.finished_at = timezone.now()
        locked.save()

    return {
        "scan_id": str(scan.id),
        "status": final_status,
        "event_count": len(events),
        "index_score": str(index_score),
    }


def execute_negative_index_scan(scan_id) -> dict:
    scan = _start_scan(scan_id)
    if scan.status in {
        NegativeIndexScan.Status.SUCCEEDED,
        NegativeIndexScan.Status.PARTIAL,
        NegativeIndexScan.Status.LIMIT_REACHED,
    }:
        return {"scan_id": str(scan.id), "status": scan.status}

    started = time_module.monotonic()
    try:
        with BaiduSearchProvider() as provider:
            payload = run_negative_search(scan, provider=provider)
        if not payload.records and payload.provider_errors:
            raise SearchProviderError("BAIDU_SEARCH_NO_USABLE_RESULTS")

        degraded = payload.partial
        NegativeIndexScan.objects.filter(pk=scan.pk).update(
            stage=NegativeIndexScan.Stage.CLASSIFYING
        )
        candidates = _build_candidates(payload)
        current_progress = (
            NegativeIndexScan.objects.filter(pk=scan.pk).values_list("progress", flat=True).first()
            or {}
        )
        NegativeIndexScan.objects.filter(pk=scan.pk).update(
            candidate_count=len(candidates),
            progress={**current_progress, "candidates": len(candidates)},
        )

        classification_degraded, ai_metadata = _classify_candidates(
            candidates,
            payload.context,
        )
        degraded = degraded or classification_degraded

        NegativeIndexScan.objects.filter(pk=scan.pk).update(stage=NegativeIndexScan.Stage.VERIFYING)
        verification_degraded, verified_count, ai_metadata = _verify_candidates(
            candidates,
            payload.context,
            ai_metadata,
        )
        degraded = degraded or verification_degraded

        negative_items = _negative_items(candidates)
        NegativeIndexScan.objects.filter(pk=scan.pk).update(
            stage=NegativeIndexScan.Stage.CLUSTERING,
            negative_item_count=len(negative_items),
            verified_item_count=verified_count,
        )
        events = _event_payloads(negative_items)
        NegativeIndexScan.objects.filter(pk=scan.pk).update(stage=NegativeIndexScan.Stage.SCORING)

        final_status = NegativeIndexScan.Status.SUCCEEDED
        if payload.limit_reached:
            final_status = NegativeIndexScan.Status.LIMIT_REACHED
        elif degraded:
            final_status = NegativeIndexScan.Status.PARTIAL

        return _persist_result(
            scan=scan,
            payload=payload,
            candidates=candidates,
            negative_items=negative_items,
            events=events,
            verified_count=verified_count,
            ai_metadata=ai_metadata,
            final_status=final_status,
            started=started,
        )
    except SearchProviderError as exc:
        fail_negative_index_scan(scan.id, exc.code)
        raise
    except Exception:
        fail_negative_index_scan(scan.id)
        raise
