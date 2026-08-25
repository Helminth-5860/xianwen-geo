from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from apps.website_audits.browser_runner import BrowserPageInput, run_browser_audit


class Command(BaseCommand):
    help = "Run a real Chromium browser audit smoke test without writing database records."

    def add_arguments(self, parser):
        parser.add_argument("url")
        parser.add_argument(
            "--profile",
            action="append",
            choices=("mobile", "desktop"),
            dest="profiles",
        )
        parser.add_argument("--timeout", type=int, default=30)
        parser.add_argument("--settle-ms", type=int, default=1200)

    def handle(self, *args, **options):
        url = options["url"]
        profiles = tuple(options["profiles"] or ("mobile", "desktop"))
        self.stdout.write(f"开始 Chromium 浏览器检测：{url}")
        try:
            results = run_browser_audit(
                [
                    BrowserPageInput(
                        page_id="smoke",
                        url=url,
                        static_text_characters=0,
                        static_title="",
                        static_meta_description="",
                        static_canonical_url="",
                        static_schema_types=(),
                    )
                ],
                profiles=profiles,
                timeout_seconds=max(1, options["timeout"]),
                settle_ms=max(0, options["settle_ms"]),
            )
        except Exception as exc:
            raise CommandError(f"浏览器检测启动失败：{type(exc).__name__}: {exc}") from exc

        for result in results:
            payload = {
                "profile": result.profile,
                "status": result.status,
                "final_url": result.final_url,
                "failure_code": result.failure_code,
                "navigation_ms": result.navigation_ms,
                "ttfb_ms": result.ttfb_ms,
                "fcp_ms": result.fcp_ms,
                "lcp_ms": result.lcp_ms,
                "cls": result.cls,
                "tbt_ms": result.tbt_ms,
                "requests": result.request_count,
                "failed_requests": result.failed_request_count,
                "blocked_requests": result.blocked_request_count,
                "transfer_bytes": result.transfer_bytes,
                "dom_nodes": result.dom_nodes,
                "rendered_text_characters": result.rendered_text_characters,
                "rendered_title": result.rendered_title,
                "rendered_schema_types": list(result.rendered_schema_types),
                "visible_images": result.visible_image_count,
                "images_without_alt": result.images_without_alt,
            }
            self.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))

        if any(result.status != "succeeded" for result in results):
            raise CommandError("至少一个浏览器样本失败。")
        self.stdout.write(self.style.SUCCESS("Chromium 浏览器检测烟雾测试通过。"))
