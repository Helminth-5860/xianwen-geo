from __future__ import annotations

import json
from time import monotonic

import httpx

from apps.ai.contracts import (
    AdapterCredential,
    AIAdapterDescriptor,
    AIAdapterRequest,
    AIAdapterResponse,
    AIAdapterTiming,
    AIFinishReason,
    AIModelCapability,
    AIModelIdentity,
    AIUsage,
    CredentialResolver,
)
from apps.ai.credentials import DatabaseCredentialResolver
from apps.ai.detection import DetectionOutput, DetectionPayload
from apps.ai.errors import AIAdapterError, AIAdapterErrorCategory
from apps.ai.exceptions import AICredentialCryptoFailure, AICredentialStateConflict
from apps.ai.registry import AIModelRegistry, model_registry
from apps.ai.semantic_scoring import (
    SemanticScoringOutput,
    SemanticScoringPayload,
    SemanticScoringSchemaError,
    build_semantic_scoring_messages,
    parse_semantic_scoring_output,
)

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_CHAT_PATH = "/chat/completions"
DEEPSEEK_ADAPTER_VERSION = "deepseek-chat-completions-v1"
DEEPSEEK_PROMPT_VERSION = "geo-detection-v1"
DEEPSEEK_SEMANTIC_ADAPTER_VERSION = "deepseek-semantic-scoring-v1"
DEEPSEEK_SEMANTIC_PROMPT_VERSION = "geo-semantic-scoring-v1"
DEEPSEEK_SEMANTIC_PROVIDER_MODEL_ID = "deepseek-chat"
DEEPSEEK_SEMANTIC_TEMPERATURE = 0.1
DEEPSEEK_SEMANTIC_MAX_OUTPUT_TOKENS = 2400
MAX_PROVIDER_RESPONSE_BYTES = 2_000_000

DEEPSEEK_DESCRIPTOR = AIAdapterDescriptor(
    identity=AIModelIdentity(provider_key="deepseek", model_key="deepseek"),
    capabilities=frozenset({AIModelCapability.GEO_DETECTION}),
    adapter_version=DEEPSEEK_ADAPTER_VERSION,
    prompt_version=DEEPSEEK_PROMPT_VERSION,
    is_mock=False,
    is_available=True,
)

DEEPSEEK_SEMANTIC_DESCRIPTOR = AIAdapterDescriptor(
    identity=AIModelIdentity(provider_key="deepseek", model_key="deepseek"),
    capabilities=frozenset({AIModelCapability.SEMANTIC_SCORING}),
    adapter_version=DEEPSEEK_SEMANTIC_ADAPTER_VERSION,
    prompt_version=DEEPSEEK_SEMANTIC_PROMPT_VERSION,
    is_mock=False,
    is_available=True,
)

HTTP_STATUS_CATEGORIES: dict[int, tuple[AIAdapterErrorCategory, str]] = {
    400: (AIAdapterErrorCategory.INVALID_REQUEST, "AI_DEEPSEEK_INVALID_REQUEST"),
    401: (AIAdapterErrorCategory.AUTHENTICATION, "AI_DEEPSEEK_AUTHENTICATION"),
    402: (AIAdapterErrorCategory.QUOTA_EXHAUSTED, "AI_DEEPSEEK_QUOTA_EXHAUSTED"),
    403: (AIAdapterErrorCategory.PERMISSION, "AI_DEEPSEEK_PERMISSION"),
    404: (AIAdapterErrorCategory.MODEL_UNAVAILABLE, "AI_DEEPSEEK_MODEL_UNAVAILABLE"),
    422: (AIAdapterErrorCategory.INVALID_REQUEST, "AI_DEEPSEEK_INVALID_REQUEST"),
    429: (AIAdapterErrorCategory.RATE_LIMIT, "AI_DEEPSEEK_RATE_LIMIT"),
    500: (AIAdapterErrorCategory.PROVIDER_INTERNAL, "AI_DEEPSEEK_PROVIDER_INTERNAL"),
    503: (
        AIAdapterErrorCategory.TEMPORARY_PROVIDER_FAILURE,
        "AI_DEEPSEEK_TEMPORARY_PROVIDER_FAILURE",
    ),
}


def _http_error(status_code: int) -> AIAdapterError:
    mapped = HTTP_STATUS_CATEGORIES.get(status_code)
    if mapped is not None:
        category, stable_code = mapped
        return AIAdapterError(
            category,
            stable_code=stable_code,
            retryable=False if status_code == 404 else None,
        )
    if status_code >= 500:
        return AIAdapterError(
            AIAdapterErrorCategory.TEMPORARY_PROVIDER_FAILURE,
            stable_code="AI_DEEPSEEK_TEMPORARY_PROVIDER_FAILURE",
        )
    return AIAdapterError(
        AIAdapterErrorCategory.PERMANENT_PROVIDER_FAILURE,
        stable_code="AI_DEEPSEEK_REQUEST_REJECTED",
        retryable=False,
    )


def _int(value: object) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _safe_optional_text(value: object, *, maximum: int = 128) -> str | None:
    if not isinstance(value, str) or not value or len(value) > maximum:
        return None
    if any(ord(character) < 32 for character in value):
        return None
    return value


def _map_finish_reason(value: object) -> AIFinishReason:
    if value == "stop":
        return AIFinishReason.STOP
    if value == "length":
        return AIFinishReason.LENGTH
    if value == "content_filter":
        return AIFinishReason.CONTENT_FILTER
    if value == "tool_calls":
        return AIFinishReason.TOOL_CALL
    if value == "insufficient_system_resource":
        raise AIAdapterError(
            AIAdapterErrorCategory.PROVIDER_INTERNAL,
            stable_code="AI_DEEPSEEK_SYSTEM_RESOURCE",
        )
    return AIFinishReason.UNKNOWN


class DeepSeekDetectionAdapter:
    descriptor = DEEPSEEK_DESCRIPTOR
    supports_web_search = False
    supports_structured_citations = False

    def __init__(
        self,
        *,
        credential_resolver: CredentialResolver | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._credential_resolver = credential_resolver or DatabaseCredentialResolver()
        self._transport = transport

    def _resolve_credential(self) -> AdapterCredential:
        try:
            return self._credential_resolver.resolve(self.descriptor.identity.provider_key)
        except AICredentialStateConflict:
            raise AIAdapterError(
                AIAdapterErrorCategory.CONFIGURATION_UNAVAILABLE,
                stable_code="AI_DEEPSEEK_CREDENTIAL_UNAVAILABLE",
                retryable=False,
            ) from None
        except AICredentialCryptoFailure:
            raise AIAdapterError(
                AIAdapterErrorCategory.CONFIGURATION_UNAVAILABLE,
                stable_code="AI_DEEPSEEK_CREDENTIAL_CRYPTO_FAILURE",
                retryable=False,
            ) from None

    def _request_body(self, payload: DetectionPayload) -> dict[str, object]:
        body: dict[str, object] = {
            "model": payload.provider_model_id,
            "messages": [
                {"role": "system", "content": payload.system_prompt},
                {"role": "user", "content": payload.user_question},
            ],
            "stream": False,
            "thinking": {"type": "disabled"},
            "temperature": float(payload.temperature),
        }
        if payload.max_output_tokens is not None:
            body["max_tokens"] = payload.max_output_tokens
        return body

    def invoke(
        self, request: AIAdapterRequest[DetectionPayload]
    ) -> AIAdapterResponse[DetectionOutput]:
        if (
            request.identity != self.descriptor.identity
            or request.capability != AIModelCapability.GEO_DETECTION
            or request.adapter_version != self.descriptor.adapter_version
            or request.prompt_version != self.descriptor.prompt_version
            or not isinstance(request.payload, DetectionPayload)
        ):
            raise AIAdapterError(
                AIAdapterErrorCategory.INVALID_REQUEST,
                stable_code="AI_DEEPSEEK_REQUEST_INVALID",
                retryable=False,
            )

        credential = self._resolve_credential()
        started = monotonic()
        client = httpx.Client(
            base_url=DEEPSEEK_BASE_URL,
            follow_redirects=False,
            trust_env=False,
            transport=self._transport,
            timeout=float(request.timeout_seconds),
        )
        try:
            response = client.post(
                DEEPSEEK_CHAT_PATH,
                headers={
                    "Authorization": f"Bearer {credential.value}",
                    "Content-Type": "application/json",
                },
                json=self._request_body(request.payload),
            )
        except httpx.TimeoutException:
            raise AIAdapterError(
                AIAdapterErrorCategory.TIMEOUT,
                stable_code="AI_DEEPSEEK_TIMEOUT",
            ) from None
        except httpx.NetworkError:
            raise AIAdapterError(
                AIAdapterErrorCategory.NETWORK,
                stable_code="AI_DEEPSEEK_NETWORK",
            ) from None
        except httpx.HTTPError:
            raise AIAdapterError(
                AIAdapterErrorCategory.NETWORK,
                stable_code="AI_DEEPSEEK_HTTP_TRANSPORT",
            ) from None
        finally:
            if self._transport is None:
                client.close()

        latency_ms = max(0, int((monotonic() - started) * 1000))
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
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            raise AIAdapterError(
                AIAdapterErrorCategory.RESPONSE_PARSE,
                stable_code="AI_DEEPSEEK_RESPONSE_INVALID",
                retryable=False,
            ) from None

        if not isinstance(data, dict):
            raise AIAdapterError(
                AIAdapterErrorCategory.RESPONSE_PARSE,
                stable_code="AI_DEEPSEEK_RESPONSE_INVALID",
                retryable=False,
            )

        choices = data.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise AIAdapterError(
                AIAdapterErrorCategory.RESPONSE_PARSE,
                stable_code="AI_DEEPSEEK_RESPONSE_INVALID",
                retryable=False,
            )

        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, dict):
            raise AIAdapterError(
                AIAdapterErrorCategory.RESPONSE_PARSE,
                stable_code="AI_DEEPSEEK_RESPONSE_INVALID",
                retryable=False,
            )
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise AIAdapterError(
                AIAdapterErrorCategory.RESPONSE_PARSE,
                stable_code="AI_DEEPSEEK_RESPONSE_EMPTY",
                retryable=False,
            )

        usage_data = data.get("usage")
        if not isinstance(usage_data, dict):
            raise AIAdapterError(
                AIAdapterErrorCategory.RESPONSE_PARSE,
                stable_code="AI_DEEPSEEK_USAGE_INVALID",
                retryable=False,
            )
        input_tokens = _int(usage_data.get("prompt_tokens"))
        output_tokens = _int(usage_data.get("completion_tokens"))
        total_tokens = _int(usage_data.get("total_tokens"))
        if input_tokens is None or output_tokens is None or total_tokens is None:
            raise AIAdapterError(
                AIAdapterErrorCategory.RESPONSE_PARSE,
                stable_code="AI_DEEPSEEK_USAGE_INVALID",
                retryable=False,
            )

        provider_model_id = _safe_optional_text(data.get("model"), maximum=255)
        if provider_model_id is None:
            raise AIAdapterError(
                AIAdapterErrorCategory.RESPONSE_PARSE,
                stable_code="AI_DEEPSEEK_MODEL_ID_INVALID",
                retryable=False,
            )

        finish_reason = _map_finish_reason(choice.get("finish_reason"))
        provider_request_id = _safe_optional_text(data.get("id"))
        metadata: dict[str, object] = {
            "provider_model_id": provider_model_id,
        }
        system_fingerprint = _safe_optional_text(data.get("system_fingerprint"))
        if system_fingerprint is not None:
            metadata["system_fingerprint"] = system_fingerprint
        cache_hit = _int(usage_data.get("prompt_cache_hit_tokens"))
        cache_miss = _int(usage_data.get("prompt_cache_miss_tokens"))
        if cache_hit is not None:
            metadata["prompt_cache_hit_tokens"] = cache_hit
        if cache_miss is not None:
            metadata["prompt_cache_miss_tokens"] = cache_miss

        output = DetectionOutput(
            provider_model_id=provider_model_id,
            raw_text=content,
            citations=(),
            web_search_requested=request.payload.web_search_requested,
            web_search_used=False,
            degraded=request.payload.web_search_requested,
        )
        return AIAdapterResponse(
            request_id=request.request_id,
            identity=self.descriptor.identity,
            output=output,
            provider_request_id=provider_request_id,
            usage=AIUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
            ),
            timing=AIAdapterTiming(latency_ms=latency_ms),
            finish_reason=finish_reason,
            sanitized_provider_metadata=metadata,
        )


class DeepSeekSemanticScoringAdapter:
    descriptor = DEEPSEEK_SEMANTIC_DESCRIPTOR

    def __init__(
        self,
        *,
        credential_resolver: CredentialResolver | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._credential_resolver = credential_resolver or DatabaseCredentialResolver()
        self._transport = transport

    def _resolve_credential(self) -> AdapterCredential:
        try:
            return self._credential_resolver.resolve(self.descriptor.identity.provider_key)
        except AICredentialStateConflict:
            raise AIAdapterError(
                AIAdapterErrorCategory.CONFIGURATION_UNAVAILABLE,
                stable_code="AI_DEEPSEEK_CREDENTIAL_UNAVAILABLE",
                retryable=False,
            ) from None
        except AICredentialCryptoFailure:
            raise AIAdapterError(
                AIAdapterErrorCategory.CONFIGURATION_UNAVAILABLE,
                stable_code="AI_DEEPSEEK_CREDENTIAL_CRYPTO_FAILURE",
                retryable=False,
            ) from None

    def _request_body(self, payload: SemanticScoringPayload) -> dict[str, object]:
        system_message, user_message = build_semantic_scoring_messages(payload)
        return {
            "model": DEEPSEEK_SEMANTIC_PROVIDER_MODEL_ID,
            "messages": [system_message, user_message],
            "stream": False,
            "thinking": {"type": "disabled"},
            "temperature": DEEPSEEK_SEMANTIC_TEMPERATURE,
            "max_tokens": DEEPSEEK_SEMANTIC_MAX_OUTPUT_TOKENS,
            "response_format": {"type": "json_object"},
        }

    def invoke(
        self, request: AIAdapterRequest[SemanticScoringPayload]
    ) -> AIAdapterResponse[SemanticScoringOutput]:
        if (
            request.identity != self.descriptor.identity
            or request.capability != AIModelCapability.SEMANTIC_SCORING
            or request.adapter_version != self.descriptor.adapter_version
            or request.prompt_version != self.descriptor.prompt_version
            or not isinstance(request.payload, SemanticScoringPayload)
        ):
            raise AIAdapterError(
                AIAdapterErrorCategory.INVALID_REQUEST,
                stable_code="AI_DEEPSEEK_SEMANTIC_REQUEST_INVALID",
                retryable=False,
            )

        credential = self._resolve_credential()
        started = monotonic()
        client = httpx.Client(
            base_url=DEEPSEEK_BASE_URL,
            follow_redirects=False,
            trust_env=False,
            transport=self._transport,
            timeout=float(request.timeout_seconds),
        )
        total_input_tokens = 0
        total_output_tokens = 0
        total_tokens = 0

        try:
            for attempt in (1, 2):
                try:
                    response = client.post(
                        DEEPSEEK_CHAT_PATH,
                        headers={
                            "Authorization": f"Bearer {credential.value}",
                            "Content-Type": "application/json",
                        },
                        json=self._request_body(request.payload),
                    )
                except httpx.TimeoutException:
                    raise AIAdapterError(
                        AIAdapterErrorCategory.TIMEOUT,
                        stable_code="AI_DEEPSEEK_TIMEOUT",
                    ) from None
                except httpx.NetworkError:
                    raise AIAdapterError(
                        AIAdapterErrorCategory.NETWORK,
                        stable_code="AI_DEEPSEEK_NETWORK",
                    ) from None
                except httpx.HTTPError:
                    raise AIAdapterError(
                        AIAdapterErrorCategory.NETWORK,
                        stable_code="AI_DEEPSEEK_HTTP_TRANSPORT",
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
                except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                    raise AIAdapterError(
                        AIAdapterErrorCategory.RESPONSE_PARSE,
                        stable_code="AI_DEEPSEEK_RESPONSE_INVALID",
                        retryable=False,
                    ) from None
                if not isinstance(data, dict):
                    raise AIAdapterError(
                        AIAdapterErrorCategory.RESPONSE_PARSE,
                        stable_code="AI_DEEPSEEK_RESPONSE_INVALID",
                        retryable=False,
                    )

                choices = data.get("choices")
                if (
                    not isinstance(choices, list)
                    or len(choices) != 1
                    or not isinstance(choices[0], dict)
                ):
                    raise AIAdapterError(
                        AIAdapterErrorCategory.RESPONSE_PARSE,
                        stable_code="AI_DEEPSEEK_RESPONSE_INVALID",
                        retryable=False,
                    )
                choice = choices[0]
                message = choice.get("message")
                if not isinstance(message, dict):
                    raise AIAdapterError(
                        AIAdapterErrorCategory.RESPONSE_PARSE,
                        stable_code="AI_DEEPSEEK_RESPONSE_INVALID",
                        retryable=False,
                    )
                content = message.get("content")
                output: SemanticScoringOutput | None = None
                if not isinstance(content, str) or not content.strip():
                    schema_error = True
                else:
                    try:
                        output = parse_semantic_scoring_output(
                            content,
                            citation_count=len(request.payload.citations),
                        )
                    except SemanticScoringSchemaError:
                        schema_error = True
                    else:
                        schema_error = False

                usage_data = data.get("usage")
                if not isinstance(usage_data, dict):
                    raise AIAdapterError(
                        AIAdapterErrorCategory.RESPONSE_PARSE,
                        stable_code="AI_DEEPSEEK_USAGE_INVALID",
                        retryable=False,
                    )
                input_tokens = _int(usage_data.get("prompt_tokens"))
                output_tokens = _int(usage_data.get("completion_tokens"))
                response_total_tokens = _int(usage_data.get("total_tokens"))
                if input_tokens is None or output_tokens is None or response_total_tokens is None:
                    raise AIAdapterError(
                        AIAdapterErrorCategory.RESPONSE_PARSE,
                        stable_code="AI_DEEPSEEK_USAGE_INVALID",
                        retryable=False,
                    )
                total_input_tokens += input_tokens
                total_output_tokens += output_tokens
                total_tokens += response_total_tokens

                if schema_error:
                    if attempt == 1:
                        continue
                    raise AIAdapterError(
                        AIAdapterErrorCategory.RESPONSE_PARSE,
                        stable_code="AI_DEEPSEEK_SEMANTIC_SCHEMA_INVALID",
                        retryable=False,
                    )

                if output is None:
                    raise AIAdapterError(
                        AIAdapterErrorCategory.RESPONSE_PARSE,
                        stable_code="AI_DEEPSEEK_SEMANTIC_SCHEMA_INVALID",
                        retryable=False,
                    )

                provider_model_id = _safe_optional_text(data.get("model"), maximum=255)
                if provider_model_id is None:
                    raise AIAdapterError(
                        AIAdapterErrorCategory.RESPONSE_PARSE,
                        stable_code="AI_DEEPSEEK_MODEL_ID_INVALID",
                        retryable=False,
                    )
                if provider_model_id != DEEPSEEK_SEMANTIC_PROVIDER_MODEL_ID:
                    raise AIAdapterError(
                        AIAdapterErrorCategory.RESPONSE_PARSE,
                        stable_code="AI_DEEPSEEK_SEMANTIC_MODEL_VERSION_MISMATCH",
                        retryable=False,
                    )

                finish_reason = _map_finish_reason(choice.get("finish_reason"))
                provider_request_id = _safe_optional_text(data.get("id"))
                metadata: dict[str, object] = {
                    "provider_model_id": provider_model_id,
                    "semantic_attempt_count": attempt,
                }
                system_fingerprint = _safe_optional_text(data.get("system_fingerprint"))
                if system_fingerprint is not None:
                    metadata["system_fingerprint"] = system_fingerprint

                return AIAdapterResponse(
                    request_id=request.request_id,
                    identity=self.descriptor.identity,
                    output=output,
                    provider_request_id=provider_request_id,
                    usage=AIUsage(
                        input_tokens=total_input_tokens,
                        output_tokens=total_output_tokens,
                        total_tokens=total_tokens,
                        request_count=attempt,
                    ),
                    timing=AIAdapterTiming(latency_ms=max(0, int((monotonic() - started) * 1000))),
                    finish_reason=finish_reason,
                    sanitized_provider_metadata=metadata,
                )
        finally:
            if self._transport is None:
                client.close()

        raise AIAdapterError(
            AIAdapterErrorCategory.RESPONSE_PARSE,
            stable_code="AI_DEEPSEEK_SEMANTIC_SCHEMA_INVALID",
            retryable=False,
        )


def register_deepseek_adapter(registry: AIModelRegistry = model_registry) -> None:
    registry.register(DEEPSEEK_DESCRIPTOR, DeepSeekDetectionAdapter)
    registry.register(DEEPSEEK_SEMANTIC_DESCRIPTOR, DeepSeekSemanticScoringAdapter)
