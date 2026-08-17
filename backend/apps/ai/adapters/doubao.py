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

DOUBAO_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DOUBAO_RESPONSES_PATH = "/responses"
DOUBAO_ADAPTER_VERSION = "doubao-responses-v1"
DOUBAO_PROMPT_VERSION = "geo-detection-v1"
MAX_PROVIDER_RESPONSE_BYTES = 2_000_000

DOUBAO_DESCRIPTOR = AIAdapterDescriptor(
    identity=AIModelIdentity(provider_key="doubao", model_key="doubao"),
    capabilities=frozenset({AIModelCapability.GEO_DETECTION}),
    adapter_version=DOUBAO_ADAPTER_VERSION,
    prompt_version=DOUBAO_PROMPT_VERSION,
    is_mock=False,
    is_available=True,
)

HTTP_STATUS_CATEGORIES: dict[int, tuple[AIAdapterErrorCategory, str]] = {
    400: (AIAdapterErrorCategory.INVALID_REQUEST, "AI_DOUBAO_INVALID_REQUEST"),
    401: (AIAdapterErrorCategory.AUTHENTICATION, "AI_DOUBAO_AUTHENTICATION"),
    402: (AIAdapterErrorCategory.QUOTA_EXHAUSTED, "AI_DOUBAO_QUOTA_EXHAUSTED"),
    403: (AIAdapterErrorCategory.PERMISSION, "AI_DOUBAO_PERMISSION"),
    404: (AIAdapterErrorCategory.MODEL_UNAVAILABLE, "AI_DOUBAO_MODEL_UNAVAILABLE"),
    408: (AIAdapterErrorCategory.TIMEOUT, "AI_DOUBAO_TIMEOUT"),
    422: (AIAdapterErrorCategory.INVALID_REQUEST, "AI_DOUBAO_INVALID_REQUEST"),
    429: (AIAdapterErrorCategory.RATE_LIMIT, "AI_DOUBAO_RATE_LIMIT"),
    500: (AIAdapterErrorCategory.PROVIDER_INTERNAL, "AI_DOUBAO_PROVIDER_INTERNAL"),
    502: (
        AIAdapterErrorCategory.TEMPORARY_PROVIDER_FAILURE,
        "AI_DOUBAO_TEMPORARY_PROVIDER_FAILURE",
    ),
    503: (
        AIAdapterErrorCategory.TEMPORARY_PROVIDER_FAILURE,
        "AI_DOUBAO_TEMPORARY_PROVIDER_FAILURE",
    ),
    504: (AIAdapterErrorCategory.TIMEOUT, "AI_DOUBAO_TIMEOUT"),
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
            stable_code="AI_DOUBAO_TEMPORARY_PROVIDER_FAILURE",
        )
    return AIAdapterError(
        AIAdapterErrorCategory.PERMANENT_PROVIDER_FAILURE,
        stable_code="AI_DOUBAO_REQUEST_REJECTED",
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


def _response_text(data: dict[str, object]) -> str:
    output = data.get("output")
    if not isinstance(output, list):
        raise AIAdapterError(
            AIAdapterErrorCategory.RESPONSE_PARSE,
            stable_code="AI_DOUBAO_RESPONSE_INVALID",
            retryable=False,
        )

    messages = [
        item
        for item in output
        if isinstance(item, dict)
        and item.get("type") == "message"
        and item.get("role") == "assistant"
    ]
    if len(messages) != 1:
        raise AIAdapterError(
            AIAdapterErrorCategory.RESPONSE_PARSE,
            stable_code="AI_DOUBAO_RESPONSE_INVALID",
            retryable=False,
        )
    content = messages[0].get("content")
    if not isinstance(content, list):
        raise AIAdapterError(
            AIAdapterErrorCategory.RESPONSE_PARSE,
            stable_code="AI_DOUBAO_RESPONSE_INVALID",
            retryable=False,
        )
    text_parts: list[str] = []
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "output_text":
            continue
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            raise AIAdapterError(
                AIAdapterErrorCategory.RESPONSE_PARSE,
                stable_code="AI_DOUBAO_RESPONSE_EMPTY",
                retryable=False,
            )
        text_parts.append(text)
    if not text_parts:
        raise AIAdapterError(
            AIAdapterErrorCategory.RESPONSE_PARSE,
            stable_code="AI_DOUBAO_RESPONSE_EMPTY",
            retryable=False,
        )
    return "".join(text_parts)


class DoubaoDetectionAdapter:
    descriptor = DOUBAO_DESCRIPTOR
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
                stable_code="AI_DOUBAO_CREDENTIAL_UNAVAILABLE",
                retryable=False,
            ) from None
        except AICredentialCryptoFailure:
            raise AIAdapterError(
                AIAdapterErrorCategory.CONFIGURATION_UNAVAILABLE,
                stable_code="AI_DOUBAO_CREDENTIAL_CRYPTO_FAILURE",
                retryable=False,
            ) from None

    def _request_body(self, payload: DetectionPayload) -> dict[str, object]:
        body: dict[str, object] = {
            "model": payload.provider_model_id,
            "instructions": payload.system_prompt,
            "input": payload.user_question,
            "stream": False,
            "store": False,
            "thinking": {"type": "disabled"},
            "temperature": float(payload.temperature),
        }
        if payload.max_output_tokens is not None:
            body["max_output_tokens"] = payload.max_output_tokens
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
                stable_code="AI_DOUBAO_REQUEST_INVALID",
                retryable=False,
            )

        credential = self._resolve_credential()
        started = monotonic()
        client = httpx.Client(
            base_url=DOUBAO_BASE_URL,
            follow_redirects=False,
            trust_env=False,
            transport=self._transport,
            timeout=float(request.timeout_seconds),
        )
        try:
            response = client.post(
                DOUBAO_RESPONSES_PATH,
                headers={
                    "Authorization": f"Bearer {credential.value}",
                    "Content-Type": "application/json",
                },
                json=self._request_body(request.payload),
            )
        except httpx.TimeoutException:
            raise AIAdapterError(
                AIAdapterErrorCategory.TIMEOUT,
                stable_code="AI_DOUBAO_TIMEOUT",
            ) from None
        except httpx.NetworkError:
            raise AIAdapterError(
                AIAdapterErrorCategory.NETWORK,
                stable_code="AI_DOUBAO_NETWORK",
            ) from None
        except httpx.HTTPError:
            raise AIAdapterError(
                AIAdapterErrorCategory.NETWORK,
                stable_code="AI_DOUBAO_HTTP_TRANSPORT",
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
                stable_code="AI_DOUBAO_RESPONSE_TOO_LARGE",
                retryable=False,
            )

        try:
            data = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            raise AIAdapterError(
                AIAdapterErrorCategory.RESPONSE_PARSE,
                stable_code="AI_DOUBAO_RESPONSE_INVALID",
                retryable=False,
            ) from None
        if (
            not isinstance(data, dict)
            or data.get("object") != "response"
            or data.get("status") != "completed"
        ):
            raise AIAdapterError(
                AIAdapterErrorCategory.RESPONSE_PARSE,
                stable_code="AI_DOUBAO_RESPONSE_INVALID",
                retryable=False,
            )

        content = _response_text(data)
        usage_data = data.get("usage")
        if not isinstance(usage_data, dict):
            raise AIAdapterError(
                AIAdapterErrorCategory.RESPONSE_PARSE,
                stable_code="AI_DOUBAO_USAGE_INVALID",
                retryable=False,
            )
        input_tokens = _int(usage_data.get("input_tokens"))
        output_tokens = _int(usage_data.get("output_tokens"))
        total_tokens = _int(usage_data.get("total_tokens"))
        if input_tokens is None or output_tokens is None or total_tokens is None:
            raise AIAdapterError(
                AIAdapterErrorCategory.RESPONSE_PARSE,
                stable_code="AI_DOUBAO_USAGE_INVALID",
                retryable=False,
            )

        provider_model_id = _safe_optional_text(data.get("model"), maximum=255)
        if provider_model_id is None:
            raise AIAdapterError(
                AIAdapterErrorCategory.RESPONSE_PARSE,
                stable_code="AI_DOUBAO_MODEL_ID_INVALID",
                retryable=False,
            )
        provider_request_id = _safe_optional_text(data.get("id"))
        metadata: dict[str, object] = {"provider_model_id": provider_model_id}
        service_tier = _safe_optional_text(data.get("service_tier"))
        if service_tier is not None:
            metadata["service_tier"] = service_tier
        input_details = usage_data.get("input_tokens_details")
        if isinstance(input_details, dict):
            cached_tokens = _int(input_details.get("cached_tokens"))
            if cached_tokens is not None:
                metadata["cached_tokens"] = cached_tokens
        output_details = usage_data.get("output_tokens_details")
        if isinstance(output_details, dict):
            reasoning_tokens = _int(output_details.get("reasoning_tokens"))
            if reasoning_tokens is not None:
                metadata["reasoning_tokens"] = reasoning_tokens

        try:
            output = DetectionOutput(
                provider_model_id=provider_model_id,
                raw_text=content,
                citations=(),
                web_search_requested=request.payload.web_search_requested,
                web_search_used=False,
                degraded=request.payload.web_search_requested,
            )
        except ValueError:
            raise AIAdapterError(
                AIAdapterErrorCategory.RESPONSE_PARSE,
                stable_code="AI_DOUBAO_RESPONSE_INVALID",
                retryable=False,
            ) from None
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
            finish_reason=AIFinishReason.STOP,
            sanitized_provider_metadata=metadata,
        )


def register_doubao_adapter(registry: AIModelRegistry = model_registry) -> None:
    registry.register(DOUBAO_DESCRIPTOR, DoubaoDetectionAdapter)
