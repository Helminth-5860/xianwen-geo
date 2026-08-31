from __future__ import annotations

from collections import Counter
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import NotFound as DRFNotFound

from apps.subjects.subject_services import subject_for_user_or_404
from apps.web_sources.url_security import canonicalize_url

from .crawler import crawl_website
from .models import WebsiteAudit, WebsiteAuditFinding, WebsiteAuditLink, WebsiteAuditPage
from .rules import evaluate_deterministic_checks


class WebsiteAuditNotFound(Exception):
    pass


class WebsiteAuditBusy(Exception):
    pass


def recover_stale_website_audits(*, user=None, subject_id=None) -> int:
    """Close static crawl records that outlived the hard execution budget.

    Celery time limits handle a live-but-stuck worker. This database reconciliation
    covers worker restarts/crashes where no process remains to update the record.
    """

    now = timezone.now()
    stale_after_seconds = max(settings.WEBSITE_AUDIT_TOTAL_TIMEOUT_SECONDS + 45, 120)
    cutoff = now - timedelta(seconds=stale_after_seconds)
    queryset = WebsiteAudit.objects.filter(
        status__in=(WebsiteAudit.Status.QUEUED, WebsiteAudit.Status.RUNNING)
    )
    if user is not None:
        queryset = queryset.filter(user=user)
    if subject_id is not None:
        queryset = queryset.filter(subject_id=subject_id)
    stale = queryset.filter(
        Q(status=WebsiteAudit.Status.QUEUED, created_at__lt=cutoff)
        | Q(status=WebsiteAudit.Status.RUNNING, started_at__lt=cutoff)
        | Q(
            status=WebsiteAudit.Status.RUNNING,
            started_at__isnull=True,
            created_at__lt=cutoff,
        )
    )
    return stale.update(
        status=WebsiteAudit.Status.FAILED,
        stable_error_code="WEBSITE_AUDIT_TIMEOUT",
        finished_at=now,
        updated_at=now,
    )


def create_website_audit(*, user, subject_id, url: str) -> WebsiteAudit:
    try:
        subject = subject_for_user_or_404(user=user, subject_id=subject_id)
    except DRFNotFound as exc:
        raise WebsiteAuditNotFound from exc
    recover_stale_website_audits(subject_id=subject.pk)
    canonical = canonicalize_url(url)
    if WebsiteAudit.objects.filter(
        subject=subject,
        status__in=(WebsiteAudit.Status.QUEUED, WebsiteAudit.Status.RUNNING),
    ).exists():
        raise WebsiteAuditBusy
    return WebsiteAudit.objects.create(
        user=user,
        subject=subject,
        root_url=canonical.value,
        root_host=canonical.host,
        max_pages=settings.WEBSITE_AUDIT_MAX_PAGES,
    )


def _start_audit(audit_id) -> WebsiteAudit:
    with transaction.atomic():
        try:
            audit = WebsiteAudit.objects.select_for_update().get(pk=audit_id)
        except WebsiteAudit.DoesNotExist as exc:
            raise WebsiteAuditNotFound from exc
        if audit.status == WebsiteAudit.Status.SUCCEEDED:
            return audit
        if audit.status not in {WebsiteAudit.Status.QUEUED, WebsiteAudit.Status.FAILED}:
            raise WebsiteAuditBusy
        audit.status = WebsiteAudit.Status.RUNNING
        audit.started_at = timezone.now()
        audit.finished_at = None
        audit.stable_error_code = ""
        audit.save(
            update_fields=("status", "started_at", "finished_at", "stable_error_code", "updated_at")
        )
        return audit


def fail_website_audit(audit_id, stable_error_code: str = "WEBSITE_AUDIT_FAILED") -> None:
    WebsiteAudit.objects.filter(pk=audit_id).update(
        status=WebsiteAudit.Status.FAILED,
        stable_error_code=stable_error_code[:64],
        finished_at=timezone.now(),
        updated_at=timezone.now(),
    )


def execute_website_audit(audit_id) -> dict[str, int | str]:
    audit = _start_audit(audit_id)
    if audit.status == WebsiteAudit.Status.SUCCEEDED:
        return {"audit_id": str(audit.id), "status": audit.status}

    try:
        result = crawl_website(
            audit.root_url,
            max_pages=audit.max_pages,
            max_sitemaps=settings.WEBSITE_AUDIT_MAX_SITEMAPS,
        )
        finding_drafts = evaluate_deterministic_checks(result)
    except Exception:
        fail_website_audit(audit.id)
        raise

    internal_by_source = Counter(
        link.source_url for link in result.links if link.is_internal
    )
    external_by_source = Counter(
        link.source_url for link in result.links if not link.is_internal
    )

    with transaction.atomic():
        locked = WebsiteAudit.objects.select_for_update().get(pk=audit.pk)
        locked.findings.all().delete()
        locked.links.all().delete()
        locked.pages.all().delete()

        page_by_url: dict[str, WebsiteAuditPage] = {}
        fetched_count = 0
        failed_count = 0
        for crawled in result.pages:
            evidence = crawled.evidence
            if crawled.status is not None:
                fetched_count += 1
            if crawled.fetch_error or (crawled.status is not None and crawled.status >= 400):
                failed_count += 1
            page = WebsiteAuditPage.objects.create(
                audit=locked,
                url=crawled.url,
                final_url=crawled.final_url,
                source=crawled.source,
                depth=crawled.depth,
                http_status=crawled.status,
                content_type=crawled.content_type,
                response_ms=crawled.response_ms,
                response_bytes=crawled.response_bytes,
                redirect_count=crawled.redirect_count,
                title=evidence.title if evidence else "",
                meta_description=evidence.meta_description if evidence else "",
                canonical_url=evidence.canonical_url if evidence else "",
                robots_meta=evidence.robots_meta if evidence else "",
                html_lang=evidence.html_lang if evidence else "",
                viewport=evidence.viewport if evidence else "",
                headings=evidence.headings if evidence else {},
                open_graph=evidence.open_graph if evidence else {},
                twitter_card=evidence.twitter_card if evidence else {},
                schema_types=evidence.schema_types if evidence else [],
                schema_entities=evidence.schema_entities if evidence else [],
                jsonld_block_count=evidence.jsonld_block_count if evidence else 0,
                jsonld_invalid_count=evidence.jsonld_invalid_count if evidence else 0,
                image_count=evidence.image_count if evidence else 0,
                image_alt_missing_count=evidence.image_alt_missing_count if evidence else 0,
                paragraph_count=evidence.paragraph_count if evidence else 0,
                list_count=evidence.list_count if evidence else 0,
                table_count=evidence.table_count if evidence else 0,
                internal_links_count=internal_by_source[crawled.url],
                external_links_count=external_by_source[crawled.url],
                text_characters=len(evidence.text) if evidence else 0,
                text_sample=(
                    evidence.text[: settings.WEBSITE_AUDIT_TEXT_SAMPLE_CHARACTERS]
                    if evidence
                    else ""
                ),
                response_sha256=crawled.response_sha256,
                fetch_error=crawled.fetch_error,
                fetched_at=timezone.now(),
            )
            page_by_url[crawled.url] = page

        link_rows = [
            WebsiteAuditLink(
                audit=locked,
                source_page=page_by_url.get(link.source_url),
                destination_url=link.destination_url,
                is_internal=link.is_internal,
                anchor_text=link.anchor_text,
                rel=link.rel,
            )
            for link in result.links
            if page_by_url.get(link.source_url) is not None
        ]
        if link_rows:
            WebsiteAuditLink.objects.bulk_create(link_rows, batch_size=1000)

        finding_rows = [
            WebsiteAuditFinding(
                audit=locked,
                category=draft.category,
                dimension=draft.dimension,
                check_key=draft.check_key,
                rule_version=draft.rule_version,
                method=draft.method,
                severity=draft.severity,
                result=draft.result,
                title=draft.title,
                summary=draft.summary,
                impact=draft.impact,
                recommendation=draft.recommendation,
                affected_count=draft.affected_count,
                evidence=draft.evidence,
            )
            for draft in finding_drafts
        ]
        if finding_rows:
            WebsiteAuditFinding.objects.bulk_create(finding_rows, batch_size=500)
        if result.timed_out:
            WebsiteAuditFinding.objects.create(
                audit=locked,
                category=WebsiteAuditFinding.Category.TECHNICAL,
                dimension="扫描覆盖",
                check_key="technical.crawl_time_budget",
                rule_version="crawler-budget-v1",
                method=WebsiteAuditFinding.Method.DETERMINISTIC,
                severity=WebsiteAuditFinding.Severity.MEDIUM,
                result=WebsiteAuditFinding.Result.WARN,
                title="整站扫描达到时间预算",
                summary=(
                    f"扫描在 {settings.WEBSITE_AUDIT_TOTAL_TIMEOUT_SECONDS} 秒时间预算内完成了 "
                    f"{fetched_count} 个页面证据，未继续等待剩余慢页面。"
                ),
                impact="报告仍基于已获取的真实页面、浏览器与语义证据生成，但未抓取页面不会被假定为正常。",
                recommendation=(
                    "如需扩大覆盖，可优化源站响应速度、Sitemap 质量与异常页面访问稳定性"
                    "后重新检测。"
                ),
                affected_count=max(0, len(result.discovered_urls) - fetched_count),
                evidence={
                    "time_budget_seconds": settings.WEBSITE_AUDIT_TOTAL_TIMEOUT_SECONDS,
                    "fetched_pages": fetched_count,
                    "discovered_urls": len(result.discovered_urls),
                },
            )

        locked.root_url = result.root_url
        locked.root_host = result.root_host
        locked.robots_url = result.robots_url
        locked.robots_status = result.robots_status
        locked.robots_text = result.robots_text
        locked.sitemap_urls = result.sitemap_urls
        locked.discovered_count = len(result.discovered_urls)
        locked.selected_count = len(result.pages)
        locked.fetched_count = fetched_count
        locked.failed_count = failed_count
        locked.internal_link_count = sum(1 for link in result.links if link.is_internal)
        locked.external_link_count = sum(1 for link in result.links if not link.is_internal)
        locked.status = WebsiteAudit.Status.SUCCEEDED
        locked.finished_at = timezone.now()
        locked.stable_error_code = ""
        locked.save()

    return {
        "audit_id": str(audit.id),
        "status": WebsiteAudit.Status.SUCCEEDED,
        "discovered": len(result.discovered_urls),
        "pages": len(result.pages),
        "links": len(result.links),
        "findings": len(finding_drafts) + (1 if result.timed_out else 0),
    }
