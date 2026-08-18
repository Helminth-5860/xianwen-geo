from __future__ import annotations

import uuid

from django.core.management.base import BaseCommand, CommandError

from ...adapters.deepseek import DeepSeekDetectionAdapter
from ...contracts import AIAdapterRequest
from ...detection import DetectionPayload
from ...errors import AIAdapterError
from ...runtime import resolve_detection_adapter

SMOKE_SYSTEM_PROMPT = "你是一个面向普通用户的中文信息助手。请直接、自然地回答用户问题。"
SMOKE_QUESTION = "请用一句中文说明什么是云计算。"


class Command(BaseCommand):
    help = "使用当前安全凭据和运行配置执行一次 DeepSeek GEO 检测 smoke；不打印回答正文或密钥。"

    def add_arguments(self, parser):
        parser.add_argument("--model-key", default="deepseek")
        parser.add_argument("--question", default=SMOKE_QUESTION)
        parser.add_argument("--max-output-tokens", type=int, default=128)

    def handle(self, *args, **options):
        try:
            snapshot, resolved = resolve_detection_adapter(model_key=options["model_key"])
            if not isinstance(resolved, DeepSeekDetectionAdapter):
                raise CommandError("Resolved adapter is not DeepSeekDetectionAdapter.")
            adapter = resolved
            request = AIAdapterRequest(
                request_id=str(uuid.uuid4()),
                correlation_id=None,
                identity=adapter.descriptor.identity,
                capability=next(iter(adapter.descriptor.capabilities)),
                adapter_version=adapter.descriptor.adapter_version,
                prompt_version=adapter.descriptor.prompt_version,
                timeout_seconds=snapshot.timeout_seconds,
                payload=DetectionPayload(
                    provider_model_id=snapshot.provider_model_id,
                    system_prompt=SMOKE_SYSTEM_PROMPT,
                    user_question=options["question"],
                    web_search_requested=False,
                    temperature=0.2,
                    max_output_tokens=options["max_output_tokens"],
                ),
            )
            response = adapter.invoke(request)
        except (AIAdapterError, ValueError) as exc:
            stable_code = getattr(exc, "stable_code", exc.__class__.__name__)
            raise CommandError(f"DeepSeek smoke failed safely: {stable_code}") from exc

        self.stdout.write(
            self.style.SUCCESS(
                "DeepSeek smoke PASS "
                f"model={response.output.provider_model_id} "
                f"finish={response.finish_reason.value} "
                f"input_tokens={response.usage.input_tokens} "
                f"output_tokens={response.usage.output_tokens} "
                f"latency_ms={response.timing.latency_ms} "
                f"answer_chars={len(response.output.raw_text)} "
                f"citations={len(response.output.citations)} "
                f"web_search_used={response.output.web_search_used} "
                f"degraded={response.output.degraded} "
                f"provider_request_id={response.provider_request_id or 'none'}"
            )
        )
