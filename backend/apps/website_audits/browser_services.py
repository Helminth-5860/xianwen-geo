from __future__ import annotations

from urllib.parse import urlsplit

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .browser_rules import evaluate_browser_checks
from .browser_runner import BrowserPageInput, normalize_profiles, run_browser_audit
from .models import (
    WebsiteAudit,
    WebsiteAuditBrowserSnapshot,
    WebsiteAuditFinding,
    WebsiteAuditPage,
)


class WebsiteBrowserAuditNotReady(Exception):
    pass


class WebsiteBrowserAuditBusy(Exception):
    pass


def _page_kind(page: WebsiteAuditPage) -> str:
    haystack = f"{urlsplit(page.url).path} {page.title}".lower()
    groups = (
        ("product", ("/product", "/products", "/service", "/services", "产品", "服务", "solution", "解决方案")),
        ("faq", ("/faq", "faq", "常见问题", "问答", "questions")),
        ("about", ("/about", "关于", "公司介绍", "品牌介绍", "company")),
        ("article", ("/blog", "/news", "/article", "新闻", "资讯", "博客", "文章")),
        ("contact", ("/contact", "联系我们", "联系方式")),
    )
    for kind, terms in groups:
        if any(term in haystack for term in terms):
            return kind
    return "other"


def select_browser_pages(audit: WebsiteAudit, max_pages: int) -> list[WebsiteAuditPage]:
    candidates = list(audit.pages.filter(http_status=200, fetch_error="").order_by("depth", "url"))
    candidates = [
        page
        for page in candidates
        if page.content_type.split(";", 1)[0].strip().lower()
        in {"text/html", "application/xhtml+xml"}
    ]
    if not candidates or max_pages <= 0:
        return []

    selected: list[WebsiteAuditPage] = []
    selected_ids: set[str] = set()

    def add(page: WebsiteAuditPage | None) -> None:
        if page is None or str(page.id) in selected_ids or len(selected) >= max_pages:
            return
        selected.append(page)
        selected_ids.add(str(page.id))

    add(next((page for page in candidates if page.source == WebsiteAuditPage.Source.ROOT), None))

    # Ensure the browser sample represents different business page intents rather than
    # merely taking the first N URLs from a sitemap.
    for kind in ("product", "faq", "about", "article", "contact"):
        matches = [page for page in candidates if _page_kind(page) == kind]
        if matches:
            matches.sort(
                key=lambda page: (
                    page.depth,
                    0 if page.source == WebsiteAuditPage.Source.SITEMAP else 1,
                    -page.internal_links_count,
                    page.url,
                )
            )
            add(matches[0])

    remaining = sorted(
        candidates,
        key=lambda page: (
            page.depth,
            0 if page.source == WebsiteAuditPage.Source.SITEMAP else 1,
            -page.internal_links_count,
            -page.text_characters,
            page.url,
        ),
    )
    for page in remaining:
        add(page)
        if len(selected) >= max_pages:
            break
    return selected


def queue_browser_audit(audit_id) -> bool:
    profiles = list(normalize_profiles(settings.WEBSITE_AUDIT_BROWSER_PROFILES))
    with transaction.atomic():
        audit = WebsiteAudit.objects.select_for_update().get(pk=audit_id)
        if audit.status != WebsiteAudit.Status.SUCCEEDED:
            return False
        if not settings.WEBSITE_AUDIT_BROWSER_ENABLED:
            if audit.browser_status != WebsiteAudit.BrowserStatus.SUCCEEDED:
                audit.browser_status = WebsiteAudit.BrowserStatus.DISABLED
                audit.browser_profiles = profiles
                audit.browser_finished_at = timezone.now()
                audit.save(
                    update_fields=(
                        "browser_status",
                        "browser_profiles",
                        "browser_finished_at",
                        "updated_at",
                    )
                )
            return False
        if audit.browser_status in {
            WebsiteAudit.BrowserStatus.QUEUED,
            WebsiteAudit.BrowserStatus.RUNNING,
            WebsiteAudit.BrowserStatus.SUCCEEDED,
        }:
            return False
        audit.browser_status = WebsiteAudit.BrowserStatus.QUEUED
        audit.browser_profiles = profiles
        audit.browser_selected_count = 0
        audit.browser_completed_count = 0
        audit.browser_failed_count = 0
        audit.browser_error_code = ""
        audit.browser_started_at = None
        audit.browser_finished_at = None
        audit.save(
            update_fields=(
                "browser_status",
                "browser_profiles",
                "browser_selected_count",
                "browser_completed_count",
                "browser_failed_count",
                "browser_error_code",
                "browser_started_at",
                "browser_finished_at",
                "updated_at",
            )
        )
        return True


def fail_browser_audit(audit_id, code: str = "BROWSER_AUDIT_FAILED") -> None:
    WebsiteAudit.objects.filter(pk=audit_id).update(
        browser_status=WebsiteAudit.BrowserStatus.FAILED,
        browser_error_code=code[:64],
        browser_finished_at=timezone.now(),
        updated_at=timezone.now(),
    )


def _start_browser_audit(audit_id) -> WebsiteAudit:
    with transaction.atomic():
        audit = WebsiteAudit.objects.select_for_update().get(pk=audit_id)
        if audit.status != WebsiteAudit.Status.SUCCEEDED:
            raise WebsiteBrowserAuditNotReady
        if audit.browser_status == WebsiteAudit.BrowserStatus.SUCCEEDED:
            return audit
        if audit.browser_status == WebsiteAudit.BrowserStatus.RUNNING:
            raise WebsiteBrowserAuditBusy
        if audit.browser_status not in {
            WebsiteAudit.BrowserStatus.QUEUED,
            WebsiteAudit.BrowserStatus.FAILED,
            WebsiteAudit.BrowserStatus.PARTIAL,
            WebsiteAudit.BrowserStatus.NOT_STARTED,
        }:
            raise WebsiteBrowserAuditNotReady
        audit.browser_status = WebsiteAudit.BrowserStatus.RUNNING
        audit.browser_started_at = timezone.now()
        audit.browser_finished_at = None
        audit.browser_error_code = ""
        audit.save(
            update_fields=(
                "browser_status",
                "browser_started_at",
                "browser_finished_at",
                "browser_error_code",
                "updated_at",
            )
        )
        return audit


def execute_browser_audit(audit_id) -> dict[str, int | str]:
    audit = _start_browser_audit(audit_id)
    if audit.browser_status == WebsiteAudit.BrowserStatus.SUCCEEDED:
        return {"audit_id": str(audit.id), "browser_status": audit.browser_status}

    selected_pages = select_browser_pages(audit, settings.WEBSITE_AUDIT_BROWSER_MAX_PAGES)
    profiles = normalize_profiles(audit.browser_profiles or settings.WEBSITE_AUDIT_BROWSER_PROFILES)
    if not selected_pages:
        fail_browser_audit(audit.id, "BROWSER_NO_ELIGIBLE_PAGES")
        return {
            "audit_id": str(audit.id),
            "browser_status": WebsiteAudit.BrowserStatus.FAILED,
            "samples": 0,
        }

    inputs = [
        BrowserPageInput(
            page_id=str(page.id),
            url=page.final_url or page.url,
            static_text_characters=page.text_characters,
            static_title=page.title,
            static_meta_description=page.meta_description,
            static_canonical_url=page.canonical_url,
            static_schema_types=tuple(str(item) for item in page.schema_types),
        )
        for page in selected_pages
    ]

    try:
        results = run_browser_audit(
            inputs,
            profiles=profiles,
            timeout_seconds=settings.WEBSITE_AUDIT_BROWSER_TIMEOUT_SECONDS,
            settle_ms=settings.WEBSITE_AUDIT_BROWSER_SETTLE_MS,
            max_requests=settings.WEBSITE_AUDIT_BROWSER_MAX_REQUESTS,
            max_dom_characters=settings.WEBSITE_AUDIT_BROWSER_MAX_DOM_CHARACTERS,
        )
        finding_drafts = evaluate_browser_checks(results)
    except Exception:
        fail_browser_audit(audit.id, "BROWSER_RUNTIME_FAILED")
        raise

    completed = sum(1 for item in results if item.status == "succeeded")
    failed = len(results) - completed
    if completed == len(results):
        final_status = WebsiteAudit.BrowserStatus.SUCCEEDED
        error_code = ""
    elif completed > 0:
        final_status = WebsiteAudit.BrowserStatus.PARTIAL
        error_code = "BROWSER_PARTIAL_FAILURE"
    else:
        final_status = WebsiteAudit.BrowserStatus.FAILED
        error_code = "BROWSER_ALL_SAMPLES_FAILED"

    with transaction.atomic():
        locked = WebsiteAudit.objects.select_for_update().get(pk=audit.pk)
        locked.browser_snapshots.all().delete()
        locked.findings.filter(method=WebsiteAuditFinding.Method.BROWSER).delete()
        page_by_id = {
            str(page.id): page
            for page in locked.pages.filter(id__in=[item.page_id for item in results])
        }

        snapshot_rows: list[WebsiteAuditBrowserSnapshot] = []
        for result in results:
            page = page_by_id.get(result.page_id)
            if page is None:
                continue
            snapshot_rows.append(
                WebsiteAuditBrowserSnapshot(
                    audit=locked,
                    page=page,
                    profile=result.profile,
                    status=result.status,
                    final_url=result.final_url,
                    navigation_ms=result.navigation_ms,
                    ttfb_ms=result.ttfb_ms,
                    dom_content_loaded_ms=result.dom_content_loaded_ms,
                    load_ms=result.load_ms,
                    fcp_ms=result.fcp_ms,
                    lcp_ms=result.lcp_ms,
                    cls=result.cls,
                    tbt_ms=result.tbt_ms,
                    request_count=result.request_count,
                    failed_request_count=result.failed_request_count,
                    blocked_request_count=result.blocked_request_count,
                    transfer_bytes=result.transfer_bytes,
                    cross_host_request_count=result.cross_host_request_count,
                    cross_host_transfer_bytes=result.cross_host_transfer_bytes,
                    resource_summary=result.resource_summary or {},
                    console_error_count=result.console_error_count,
                    page_error_count=result.page_error_count,
                    dom_nodes=result.dom_nodes,
                    rendered_html_characters=result.rendered_html_characters,
                    rendered_text_characters=result.rendered_text_characters,
                    static_text_characters=result.static_text_characters,
                    text_delta=result.text_delta,
                    text_growth_ratio=result.text_growth_ratio,
                    rendered_title=result.rendered_title,
                    rendered_meta_description=result.rendered_meta_description,
                    rendered_canonical_url=result.rendered_canonical_url,
                    rendered_schema_types=list(result.rendered_schema_types),
                    rendered_heading_counts=result.rendered_heading_counts or {},
                    visible_image_count=result.visible_image_count,
                    images_without_alt=result.images_without_alt,
                    failure_code=result.failure_code,
                    evidence=result.evidence or {},
                )
            )
        if snapshot_rows:
            WebsiteAuditBrowserSnapshot.objects.bulk_create(snapshot_rows, batch_size=100)

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
            WebsiteAuditFinding.objects.bulk_create(finding_rows, batch_size=100)

        locked.browser_status = final_status
        locked.browser_profiles = list(profiles)
        locked.browser_selected_count = len(results)
        locked.browser_completed_count = completed
        locked.browser_failed_count = failed
        locked.browser_error_code = error_code
        locked.browser_finished_at = timezone.now()
        locked.save(
            update_fields=(
                "browser_status",
                "browser_profiles",
                "browser_selected_count",
                "browser_completed_count",
                "browser_failed_count",
                "browser_error_code",
                "browser_finished_at",
                "updated_at",
            )
        )

    return {
        "audit_id": str(audit.id),
        "browser_status": final_status,
        "pages": len(selected_pages),
        "profiles": len(profiles),
        "samples": len(results),
        "completed": completed,
        "failed": failed,
        "findings": len(finding_drafts),
    }
