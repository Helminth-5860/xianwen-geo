from __future__ import annotations

import json
import uuid

from django.core.management.base import BaseCommand, CommandError

from apps.ai.errors import AIAdapterError
from apps.website_audits.crawler import crawl_website
from apps.website_audits.rules import evaluate_deterministic_checks
from apps.website_audits.semantic_context import SemanticAuditContext
from apps.website_audits.semantic_provider import execute_semantic_provider
from apps.website_audits.semantic_validation import SemanticAuditSchemaError


def _page_rows(result, *, maximum_pages: int, max_chars_per_page: int, max_total_chars: int):
    rows: list[dict[str, object]] = []
    used = 0
    for page in result.pages:
        evidence = page.evidence
        if (
            len(rows) >= maximum_pages
            or used >= max_total_chars
            or page.status != 200
            or page.fetch_error
            or evidence is None
            or not evidence.text.strip()
        ):
            continue
        remaining = max_total_chars - used
        text = evidence.text[: min(max_chars_per_page, remaining)]
        if not text.strip():
            continue
        rows.append(
            {
                "page_id": f"smoke-{len(rows) + 1}",
                "url": page.final_url or page.url,
                "title": evidence.title,
                "meta_description": evidence.meta_description[:1000],
                "headings": evidence.headings,
                "schema_types": evidence.schema_types,
                "text": text,
                "text_characters": len(evidence.text),
                "internal_links": sum(
                    1
                    for link in result.links
                    if link.source_url == page.url and link.is_internal
                ),
                "external_links": sum(
                    1
                    for link in result.links
                    if link.source_url == page.url and not link.is_internal
                ),
            }
        )
        used += len(text)
    return rows


def _technical_evidence(result):
    findings = evaluate_deterministic_checks(result)
    return {
        "smoke_mode": True,
        "browser_status": "not_included_in_semantic_provider_smoke",
        "deterministic_and_browser_findings": [
            {
                "method": item.method,
                "category": item.category,
                "dimension": item.dimension,
                "check_key": item.check_key,
                "severity": item.severity,
                "result": item.result,
                "title": item.title,
                "affected_count": item.affected_count,
                "evidence": item.evidence,
            }
            for item in findings[:80]
        ],
        "browser_snapshots": [],
    }


class Command(BaseCommand):
    help = "Run a real DeepSeek GEO semantic audit smoke test without writing audit records."

    def add_arguments(self, parser):
        parser.add_argument("url")
        parser.add_argument("--subject-name", default="")
        parser.add_argument("--crawl-pages", type=int, default=8)
        parser.add_argument("--semantic-pages", type=int, default=6)
        parser.add_argument("--max-chars-per-page", type=int, default=6000)
        parser.add_argument("--max-total-chars", type=int, default=30000)

    def handle(self, *args, **options):
        url = options["url"]
        subject_name = options["subject_name"].strip() or url
        crawl_pages = min(20, max(1, options["crawl_pages"]))
        semantic_pages = min(10, max(1, options["semantic_pages"]))
        max_chars_per_page = min(12000, max(1000, options["max_chars_per_page"]))
        max_total_chars = min(60000, max(5000, options["max_total_chars"]))

        self.stdout.write(f"开始公网抓取：{url}")
        try:
            crawl = crawl_website(url, max_pages=crawl_pages, max_sitemaps=10)
        except Exception as exc:
            raise CommandError(f"公网抓取失败：{type(exc).__name__}: {exc}") from exc

        pages = _page_rows(
            crawl,
            maximum_pages=semantic_pages,
            max_chars_per_page=max_chars_per_page,
            max_total_chars=max_total_chars,
        )
        if not pages:
            raise CommandError("没有得到可用于语义审计的正文页面。")

        context = SemanticAuditContext(
            subject={
                "subject_id": "semantic-smoke",
                "official_name": subject_name,
                "aliases": [],
                "products": [],
                "public_fields": {"website": crawl.root_url},
            },
            keywords=[],
            questions=[],
            pages=pages,
            technical_evidence=_technical_evidence(crawl),
            allowed_page_ids=frozenset(str(row["page_id"]) for row in pages),
            allowed_question_ids=frozenset(),
            page_url_by_id={str(row["page_id"]): str(row["url"]) for row in pages},
            page_text_by_id={str(row["page_id"]): str(row["text"]) for row in pages},
        )

        self.stdout.write(
            f"抓取完成：发现URL={len(crawl.discovered_urls)} 抓取页面={len(crawl.pages)} "
            f"语义样本={len(pages)}，开始调用 DeepSeek semantic_scoring..."
        )
        try:
            provider = execute_semantic_provider(
                audit_id=str(uuid.uuid4()),
                context=context,
            )
        except AIAdapterError as exc:
            raise CommandError(
                f"DeepSeek 调用失败：{exc.stable_code} ({exc.category.value})"
            ) from exc
        except SemanticAuditSchemaError as exc:
            raise CommandError(f"DeepSeek 返回未通过真实性校验：{exc}") from exc
        except Exception as exc:
            raise CommandError(f"语义审计失败：{type(exc).__name__}: {exc}") from exc

        result = provider.validated.result
        questions = result.get("question_assessments", [])
        answered = sum(1 for row in questions if row.get("status") == "answered")
        partial = sum(1 for row in questions if row.get("status") == "partial")
        missing = sum(1 for row in questions if row.get("status") == "missing")

        self.stdout.write("语义评分：" + json.dumps(provider.validated.scores, ensure_ascii=False, sort_keys=True))
        self.stdout.write(f"整体结论：{provider.validated.summary}")
        self.stdout.write(
            f"问题覆盖：总数={len(questions)} 完整={answered} 部分={partial} 缺失={missing}"
        )
        self.stdout.write(
            f"内容问题={len(result.get('content_findings', []))} "
            f"主题缺口={len(result.get('topic_gaps', []))} "
            f"可引用原文={len(result.get('citeable_passages', []))}"
        )
        self.stdout.write(
            f"模型={provider.provider_model_id} tokens={provider.total_tokens} "
            f"latency_ms={provider.latency_ms}"
        )
        self.stdout.write(self.style.SUCCESS("真实 DeepSeek GEO 语义烟雾测试通过。"))
