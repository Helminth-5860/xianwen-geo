from __future__ import annotations

import json
import re
from time import monotonic

import httpx

from apps.ai.content import StructuredContentOutput, StructuredContentPayload
from apps.ai.contracts import (
    AdapterCredential,
    AIAdapterDescriptor,
    AIAdapterRequest,
    AIAdapterResponse,
    AIAdapterTiming,
    AIModelCapability,
    AIModelIdentity,
    AIUsage,
    CredentialResolver,
)
from apps.ai.credentials import DatabaseCredentialResolver
from apps.ai.errors import AIAdapterError, AIAdapterErrorCategory
from apps.ai.exceptions import AICredentialCryptoFailure, AICredentialStateConflict
from apps.ai.registry import AIModelRegistry, model_registry

from .deepseek import (
    DEEPSEEK_BASE_URL,
    DEEPSEEK_CHAT_PATH,
    MAX_PROVIDER_RESPONSE_BYTES,
    _http_error,
    _int,
    _map_finish_reason,
    _safe_optional_text,
)

DEEPSEEK_STRATEGY_ADAPTER_VERSION = "deepseek-strategy-v1"
DEEPSEEK_STRATEGY_PROMPT_VERSION = "geo-improvement-strategy-v1"
DEEPSEEK_ASSISTANT_ADAPTER_VERSION = "deepseek-assistant-v1"
DEEPSEEK_ASSISTANT_PROMPT_VERSION = "subject-assistant-v1"
DEEPSEEK_ARTICLE_ADAPTER_VERSION = "deepseek-article-v1"
DEEPSEEK_ARTICLE_PROMPT_VERSION = "geo-article-content-v1"

_JSON_CODE_FENCE = re.compile(
    r"^\s*```(?:json)?\s*(?P<body>.*?)\s*```\s*$",
    re.IGNORECASE | re.DOTALL,
)


def _parse_json_object_content(content: object) -> dict:
    """Parse one JSON object while tolerating common model presentation wrappers.

    DeepSeek is asked for JSON mode, but an otherwise valid response can still be
    wrapped in a Markdown fence or a short explanatory prefix/suffix.  This helper
    deliberately does not repair values or invent missing fields; domain adapters
    remain responsible for their own strict schema validation.
    """

    if not isinstance(content, str):
        raise ValueError("content_not_text")
    candidate = content.strip()
    fenced = _JSON_CODE_FENCE.fullmatch(candidate)
    if fenced is not None:
        candidate = fenced.group("body").strip()
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        parsed = None
        for index, character in enumerate(candidate):
            if character != "{":
                continue
            try:
                value, _ = decoder.raw_decode(candidate[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                parsed = value
                break
        if parsed is None:
            raise
    if not isinstance(parsed, dict):
        raise ValueError("content_not_object")
    return parsed


DEEPSEEK_STRATEGY_DESCRIPTOR = AIAdapterDescriptor(
    identity=AIModelIdentity(provider_key="deepseek", model_key="deepseek"),
    capabilities=frozenset({AIModelCapability.IMPROVEMENT_STRATEGY}),
    adapter_version=DEEPSEEK_STRATEGY_ADAPTER_VERSION,
    prompt_version=DEEPSEEK_STRATEGY_PROMPT_VERSION,
)
DEEPSEEK_ASSISTANT_DESCRIPTOR = AIAdapterDescriptor(
    identity=AIModelIdentity(provider_key="deepseek", model_key="deepseek"),
    capabilities=frozenset({AIModelCapability.SUBJECT_ASSISTANT}),
    adapter_version=DEEPSEEK_ASSISTANT_ADAPTER_VERSION,
    prompt_version=DEEPSEEK_ASSISTANT_PROMPT_VERSION,
)
DEEPSEEK_ARTICLE_DESCRIPTOR = AIAdapterDescriptor(
    identity=AIModelIdentity(provider_key="deepseek", model_key="deepseek"),
    capabilities=frozenset({AIModelCapability.TEXT_GENERATION}),
    adapter_version=DEEPSEEK_ARTICLE_ADAPTER_VERSION,
    prompt_version=DEEPSEEK_ARTICLE_PROMPT_VERSION,
)


class _DeepSeekStructuredContentAdapter:
    descriptor: AIAdapterDescriptor

    def __init__(
        self,
        *,
        credential_resolver: CredentialResolver | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._credential_resolver = credential_resolver or DatabaseCredentialResolver()
        self._transport = transport

    def _credential(self) -> AdapterCredential:
        try:
            return self._credential_resolver.resolve("deepseek")
        except (AICredentialStateConflict, AICredentialCryptoFailure):
            raise AIAdapterError(
                AIAdapterErrorCategory.CONFIGURATION_UNAVAILABLE,
                stable_code="AI_DEEPSEEK_CREDENTIAL_UNAVAILABLE",
                retryable=False,
            ) from None

    def invoke(
        self, request: AIAdapterRequest[StructuredContentPayload]
    ) -> AIAdapterResponse[StructuredContentOutput]:
        if (
            request.identity != self.descriptor.identity
            or request.capability not in self.descriptor.capabilities
            or request.adapter_version != self.descriptor.adapter_version
            or request.prompt_version != self.descriptor.prompt_version
            or not isinstance(request.payload, StructuredContentPayload)
        ):
            raise AIAdapterError(
                AIAdapterErrorCategory.INVALID_REQUEST,
                stable_code="AI_DEEPSEEK_CONTENT_REQUEST_INVALID",
                retryable=False,
            )
        credential = self._credential()
        started = monotonic()
        client = httpx.Client(
            base_url=DEEPSEEK_BASE_URL,
            follow_redirects=False,
            trust_env=False,
            transport=self._transport,
            timeout=float(request.timeout_seconds),
        )
        try:
            try:
                response = client.post(
                    DEEPSEEK_CHAT_PATH,
                    headers={
                        "Authorization": f"Bearer {credential.value}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": request.payload.provider_model_id,
                        "messages": [
                            {"role": "system", "content": request.payload.system_prompt},
                            {
                                "role": "user",
                                "content": json.dumps(
                                    request.payload.user_payload,
                                    ensure_ascii=False,
                                    sort_keys=True,
                                ),
                            },
                        ],
                        "stream": False,
                        "thinking": {"type": "disabled"},
                        "temperature": request.payload.temperature,
                        "max_tokens": request.payload.max_output_tokens,
                        "response_format": {"type": "json_object"},
                    },
                )
            except httpx.TimeoutException:
                raise AIAdapterError(
                    AIAdapterErrorCategory.TIMEOUT,
                    stable_code="AI_DEEPSEEK_TIMEOUT",
                ) from None
            except httpx.HTTPError:
                raise AIAdapterError(
                    AIAdapterErrorCategory.NETWORK,
                    stable_code="AI_DEEPSEEK_NETWORK",
                ) from None
            if response.status_code != 200:
                raise _http_error(response.status_code)
            if len(response.content) > MAX_PROVIDER_RESPONSE_BYTES:
                raise AIAdapterError(
                    AIAdapterErrorCategory.RESPONSE_PARSE,
                    stable_code="AI_DEEPSEEK_RESPONSE_TOO_LARGE",
                    retryable=False,
                )
            try:
                data = response.json()
                choices = data["choices"]
                choice = choices[0]
                content = choice["message"]["content"]
                parsed = _parse_json_object_content(content)
                usage = data["usage"]
            except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
                raise AIAdapterError(
                    AIAdapterErrorCategory.RESPONSE_PARSE,
                    stable_code="AI_DEEPSEEK_CONTENT_SCHEMA_INVALID",
                    retryable=False,
                ) from None
            if (
                not isinstance(data, dict)
                or not isinstance(choices, list)
                or len(choices) != 1
                or not isinstance(choice, dict)
                or not isinstance(parsed, dict)
                or not isinstance(usage, dict)
            ):
                raise AIAdapterError(
                    AIAdapterErrorCategory.RESPONSE_PARSE,
                    stable_code="AI_DEEPSEEK_CONTENT_SCHEMA_INVALID",
                    retryable=False,
                )
            input_tokens = _int(usage.get("prompt_tokens"))
            output_tokens = _int(usage.get("completion_tokens"))
            total_tokens = _int(usage.get("total_tokens"))
            provider_model_id = _safe_optional_text(data.get("model"), maximum=255)
            if (
                input_tokens is None
                or output_tokens is None
                or total_tokens is None
                or provider_model_id != request.payload.provider_model_id
            ):
                raise AIAdapterError(
                    AIAdapterErrorCategory.RESPONSE_PARSE,
                    stable_code="AI_DEEPSEEK_CONTENT_SCHEMA_INVALID",
                    retryable=False,
                )
            return AIAdapterResponse(
                request_id=request.request_id,
                identity=self.descriptor.identity,
                output=StructuredContentOutput(content=parsed),
                provider_request_id=_safe_optional_text(data.get("id")),
                usage=AIUsage(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                ),
                timing=AIAdapterTiming(latency_ms=max(0, int((monotonic() - started) * 1000))),
                finish_reason=_map_finish_reason(choice.get("finish_reason")),
                sanitized_provider_metadata={"provider_model_id": provider_model_id},
            )
        finally:
            if self._transport is None:
                client.close()


# Capability adapters outside this module reuse the same hardened DeepSeek JSON transport.
DeepSeekStructuredContentAdapter = _DeepSeekStructuredContentAdapter


class DeepSeekStrategyAdapter(DeepSeekStructuredContentAdapter):
    descriptor = DEEPSEEK_STRATEGY_DESCRIPTOR


class DeepSeekSubjectAssistantAdapter(DeepSeekStructuredContentAdapter):
    descriptor = DEEPSEEK_ASSISTANT_DESCRIPTOR


class DeepSeekArticleAdapter(DeepSeekStructuredContentAdapter):
    descriptor = DEEPSEEK_ARTICLE_DESCRIPTOR


def register_deepseek_content_adapters(
    registry: AIModelRegistry = model_registry,
) -> None:
    registry.register(DEEPSEEK_STRATEGY_DESCRIPTOR, DeepSeekStrategyAdapter)
    registry.register(DEEPSEEK_ASSISTANT_DESCRIPTOR, DeepSeekSubjectAssistantAdapter)
    registry.register(DEEPSEEK_ARTICLE_DESCRIPTOR, DeepSeekArticleAdapter)
