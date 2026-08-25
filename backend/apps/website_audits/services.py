from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.subjects.models import Subject
from apps.web_sources.url_security import canonicalize_url

from .crawler import crawl_website
from .models import WebsiteAudit, WebsiteAuditLink, WebsiteAuditPage


class WebsiteAuditNotFound(Exception):
    pass


class WebsiteAuditBusy(Exception):
    pass


def create_website_audit(*, user, subject_id, url: str) -> WebsiteAudit:
    subject = Subject.objects.filter(pk=subject_id, user=user).first()
    if subject is None:
        raise WebsiteAuditNotFound
    canonical = canonicalize_url(url)
    if WebsiteAudit.objects.filter(
        user=user,
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
        audit.save(update_fields=("status", "started_at", "finished_at", "stable_error_code", "updated_at"))
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
    except Exception:
        fail_website_audit(audit.id)
        raise

    with transaction.atomic():
        locked = WebsiteAudit.objects.select_for_update().get(pk=audit.pk)
        locked.pages.all().delete()
        locked.links.all().delete()

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
                image_count=evidence.image_count if evidence else 0,
                image_alt_missing_count=evidence.image_alt_missing_count if evidence else 0,
                internal_links_count=sum(1 for link in result.links if link.source_url == crawled.url and link.is_internal),
                external_links_count=sum(1 for link in result.links if link.source_url == crawled.url and not link.is_internal),
                text_characters=len(evidence.text) if evidence else 0,
                text_sample=(evidence.text[: settings.WEBSITE_AUDIT_TEXT_SAMPLE_CHARACTERS] if evidence else ""),
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
    }
