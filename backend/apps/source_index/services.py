from __future__ import annotations

import time as time_module
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.subjects.models import Subject

from .models import SourceIndexHit, SourceIndexItem, SourceIndexScan
from .provider import BaiduSearchProvider, SearchProviderError
from .scanner import run_adaptive_scan
from .scoring import (
    calculate_index,
    classify_source,
    freshness_score,
    is_recent_30d,
    mark_cross_domain_reposts,
    relevance_score,
    source_weight,
    url_identity_hash,
    visibility_score,
)


class SourceIndexNotFound(Exception):
    pass


class SourceIndexBusy(Exception):
    pass


def recover_stale_source_index_scans(*, user=None, subject_id=None) -> int:
    total_budget = int(getattr(settings, "SOURCE_INDEX_TOTAL_TIMEOUT_SECONDS", 300))
    cutoff = timezone.now() - timedelta(seconds=max(total_budget + 90, 390))
    queryset = SourceIndexScan.objects.filter(
        status__in=(SourceIndexScan.Status.QUEUED, SourceIndexScan.Status.RUNNING)
    )
    if user is not None:
        queryset = queryset.filter(user=user)
    if subject_id is not None:
        queryset = queryset.filter(subject_id=subject_id)
    return queryset.filter(
        Q(status=SourceIndexScan.Status.QUEUED, created_at__lt=cutoff)
        | Q(status=SourceIndexScan.Status.RUNNING, started_at__lt=cutoff)
        | Q(status=SourceIndexScan.Status.RUNNING, started_at__isnull=True, created_at__lt=cutoff)
    ).update(
        status=SourceIndexScan.Status.FAILED,
        stage=SourceIndexScan.Stage.COMPLETED,
        stable_error_code="SOURCE_INDEX_TIMEOUT",
        finished_at=timezone.now(),
        updated_at=timezone.now(),
    )


def create_source_index_scan(*, user, subject_id) -> SourceIndexScan:
    subject = Subject.objects.filter(pk=subject_id, user=user).first()
    if subject is None:
        raise SourceIndexNotFound
    recover_stale_source_index_scans(user=user, subject_id=subject.pk)
    if SourceIndexScan.objects.filter(
        user=user,
        subject=subject,
        status__in=(SourceIndexScan.Status.QUEUED, SourceIndexScan.Status.RUNNING),
    ).exists():
        raise SourceIndexBusy
    try:
        return SourceIndexScan.objects.create(user=user, subject=subject)
    except IntegrityError as exc:
        # Close the race between two simultaneous POST requests for the same subject.
        raise SourceIndexBusy from exc


def _start_scan(scan_id) -> SourceIndexScan:
    with transaction.atomic():
        try:
            scan = (
                SourceIndexScan.objects.select_for_update()
                .select_related("subject", "subject__current_version")
                .get(pk=scan_id)
            )
        except SourceIndexScan.DoesNotExist as exc:
            raise SourceIndexNotFound from exc
        if scan.status in {
            SourceIndexScan.Status.SUCCEEDED,
            SourceIndexScan.Status.PARTIAL,
            SourceIndexScan.Status.LIMIT_REACHED,
        }:
            return scan
        if scan.status not in {SourceIndexScan.Status.QUEUED, SourceIndexScan.Status.FAILED}:
            raise SourceIndexBusy
        scan.status = SourceIndexScan.Status.RUNNING
        scan.stage = SourceIndexScan.Stage.PREPARING
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


def fail_source_index_scan(scan_id, stable_error_code: str = "SOURCE_INDEX_FAILED") -> None:
    SourceIndexScan.objects.filter(pk=scan_id).update(
        status=SourceIndexScan.Status.FAILED,
        stage=SourceIndexScan.Stage.COMPLETED,
        stable_error_code=stable_error_code[:100],
        finished_at=timezone.now(),
        updated_at=timezone.now(),
    )


def execute_source_index_scan(scan_id) -> dict:
    scan = _start_scan(scan_id)
    if scan.status in {
        SourceIndexScan.Status.SUCCEEDED,
        SourceIndexScan.Status.PARTIAL,
        SourceIndexScan.Status.LIMIT_REACHED,
    }:
        return {"scan_id": str(scan.id), "status": scan.status}

    execution_started = time_module.monotonic()
    try:
        with BaiduSearchProvider() as provider:
            payload = run_adaptive_scan(scan, provider=provider)
        if not payload.records and payload.provider_errors:
            raise SearchProviderError("BAIDU_SEARCH_NO_USABLE_RESULTS")

        SourceIndexScan.objects.filter(pk=scan.pk).update(stage=SourceIndexScan.Stage.CLASSIFYING)
        minimum_relevance = int(getattr(settings, "SOURCE_INDEX_MIN_RELEVANCE_SCORE", 60))
        high_weight_threshold = float(getattr(settings, "SOURCE_INDEX_HIGH_WEIGHT_SCORE", 75))
        scored: list[dict] = []
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
            visibility = visibility_score(record["best_rank"])
            freshness = freshness_score(record["published_at"])
            weight = source_weight(
                authority=authority,
                relevance=relevance,
                visibility=visibility,
                freshness=freshness,
            )
            scored.append(
                {
                    **record,
                    "source_type": source_type,
                    "authority_score": authority,
                    "relevance_score": relevance,
                    "visibility_score": visibility,
                    "freshness_score": freshness,
                    "source_weight": weight,
                    "matched_query_count": len(matched_queries),
                }
            )

        # Do not label every long title as a repost. A repost cluster exists only when
        # an equivalent normalized title is observed across at least two root domains.
        mark_cross_domain_reposts(scored)

        SourceIndexScan.objects.filter(pk=scan.pk).update(stage=SourceIndexScan.Stage.SCORING)
        index_score, factor_scores = calculate_index(scored)
        source_type_news = {
            SourceIndexItem.SourceType.NEWS_MEDIA,
            SourceIndexItem.SourceType.INDUSTRY_MEDIA,
        }
        news_media_count = sum(1 for item in scored if item["source_type"] in source_type_news)
        high_weight_count = sum(
            1 for item in scored if float(item["source_weight"]) >= high_weight_threshold
        )
        recent_30d_count = sum(1 for item in scored if is_recent_30d(item["published_at"]))
        independent_domain_count = len(
            {item["root_domain"] for item in scored if item["root_domain"]}
        )
        final_status = SourceIndexScan.Status.SUCCEEDED
        if payload.limit_reached:
            final_status = SourceIndexScan.Status.LIMIT_REACHED
        elif payload.partial:
            final_status = SourceIndexScan.Status.PARTIAL

        item_objects: list[SourceIndexItem] = []
        item_by_url: dict[str, SourceIndexItem] = {}
        for item in scored:
            obj = SourceIndexItem(
                scan=scan,
                original_url=item["original_url"],
                normalized_url=item["normalized_url"],
                normalized_url_hash=url_identity_hash(item["normalized_url"]),
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
                source_weight=item["source_weight"],
                best_rank=item["best_rank"],
                matched_query_count=item["matched_query_count"],
                repost_cluster_id=item["repost_cluster_id"],
            )
            item_objects.append(obj)
            item_by_url[item["normalized_url"]] = obj

        with transaction.atomic():
            locked = SourceIndexScan.objects.select_for_update().get(pk=scan.pk)
            if locked.items.exists() or locked.hits.exists():
                # Scan rows are immutable after a completed result exists. A task
                # retry must not duplicate evidence.
                return {"scan_id": str(locked.id), "status": locked.status}
            if item_objects:
                SourceIndexItem.objects.bulk_create(item_objects, batch_size=1000)
            hit_objects = []
            for hit in payload.hits:
                item_obj = item_by_url.get(hit["normalized_url"])
                if item_obj is None:
                    continue
                hit_objects.append(
                    SourceIndexHit(
                        scan=locked,
                        item=item_obj,
                        query=hit["query"],
                        rank=hit["rank"],
                        range_start=hit["range_start"],
                        range_end=hit["range_end"],
                    )
                )
            if hit_objects:
                SourceIndexHit.objects.bulk_create(
                    hit_objects,
                    batch_size=2000,
                    ignore_conflicts=True,
                )

            elapsed_ms = int((time_module.monotonic() - execution_started) * 1000)
            locked.status = final_status
            locked.stage = SourceIndexScan.Stage.COMPLETED
            locked.provider_request_count = payload.provider_requests
            locked.provider_error_count = payload.provider_errors
            locked.raw_result_count = payload.raw_results
            locked.unique_result_count = len(payload.records)
            locked.query_count = payload.query_count
            locked.public_source_count = len(scored)
            locked.independent_domain_count = independent_domain_count
            locked.news_media_count = news_media_count
            locked.high_weight_count = high_weight_count
            locked.recent_30d_count = recent_30d_count
            locked.index_score = index_score
            locked.factor_scores = factor_scores
            locked.progress = {
                "raw": payload.raw_results,
                "unique": len(payload.records),
                "public_sources": len(scored),
                "independent_domains": independent_domain_count,
                "news_media": news_media_count,
            }
            locked.formula_version = "source-index-v1"
            locked.stable_error_code = ""
            locked.elapsed_ms = elapsed_ms
            locked.finished_at = timezone.now()
            locked.save()

        return {
            "scan_id": str(scan.id),
            "status": final_status,
            "public_sources": len(scored),
            "independent_domains": independent_domain_count,
            "index_score": str(index_score),
        }
    except SearchProviderError as exc:
        fail_source_index_scan(scan.id, exc.code)
        raise
    except Exception:
        fail_source_index_scan(scan.id)
        raise
