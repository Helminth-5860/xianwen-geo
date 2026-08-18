from __future__ import annotations

import json
from dataclasses import dataclass
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

MAX_PROVIDER_RESPONSE_BYTES = 2_000_000


@dataclass(frozen=True)
class OpenAIChatProviderSpec:
    provider_key: str
    model_key: str
    base_url: str
    chat_path: str = "/chat/completions"
    adapter_version: str = "openai-chat-v1"
    prompt_version: str = "geo-detection-v1"

    def descriptor(self) -> AIAdapterDescriptor:
        return AIAdapterDescriptor(
            identity=AIModelIdentity(
                provider_key=self.provider_key,
                model_key=self.model_key,
            ),
            capabilities=frozenset({AIModelCapability.GEO_DETECTION}),
            adapter_version=self.adapter_version,
            prompt_version=self.prompt_version,
            is_mock=False,
            is_available=True,
        )

    @property
    def error_prefix(self) -> str:
        return f"AI_{self.provider_key.upper()}"


def _safe_optional_text(value: object, *, maximum: int = 128) -> str | None:
    if not isinstance(value, str) or not value or len(value) > maximum:
        return None
    if any(ord(character) < 32 for character in value):
        return None
    return value


def _int(value: object) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _finish_reason(value: object) -> AIFinishReason:
    if value == "stop":
        return AIFinishReason.STOP
    if value == "length":
        return AIFinishReason.LENGTH
    if value == "content_filter":
        return AIFinishReason.CONTENT_FILTER
    if value in {"tool_calls", "function_call"}:
        return AIFinishReason.TOOL_CALL
    return AIFinishReason.UNKNOWN


def _http_error(spec: OpenAIChatProviderSpec, status_code: int) -> AIAdapterError:
    prefix = spec.error_prefix
    mapped: dict[int, tuple[AIAdapterErrorCategory, str, bool | None]] = {
        400: (AIAdapterErrorCategory.INVALID_REQUEST, f"{prefix}_INVALID_REQUEST", False),
        401: (AIAdapterErrorCategory.AUTHENTICATION, f"{prefix}_AUTHENTICATION", False),
        402: (AIAdapterErrorCategory.QUOTA_EXHAUSTED, f"{prefix}_QUOTA_EXHAUSTED", False),
        403: (AIAdapterErrorCategory.PERMISSION, f"{prefix}_PERMISSION", False),
        404: (AIAdapterErrorCategory.MODEL_UNAVAILABLE, f"{prefix}_MODEL_UNAVAILABLE", False),
        408: (AIAdapterErrorCategory.TIMEOUT, f"{prefix}_TIMEOUT", None),
        409: (
            AIAdapterErrorCategory.TEMPORARY_PROVIDER_FAILURE,
            f"{prefix}_TEMPORARY_PROVIDER_FAILURE",
            None,
        ),
        422: (AIAdapterErrorCategory.INVALID_REQUEST, f"{prefix}_INVALID_REQUEST", False),
        429: (AIAdapterErrorCategory.RATE_LIMIT, f"{prefix}_RATE_LIMIT", None),
        500: (AIAdapterErrorCategory.PROVIDER_INTERNAL, f"{prefix}_PROVIDER_INTERNAL", None),
        502: (
            AIAdapterErrorCategory.TEMPORARY_PROVIDER_FAILURE,
            f"{prefix}_TEMPORARY_PROVIDER_FAILURE",
            None,
        ),
        503: (
            AIAdapterErrorCategory.TEMPORARY_PROVIDER_FAILURE,
            f"{prefix}_TEMPORARY_PROVIDER_FAILURE",
            None,
        ),
        504: (AIAdapterErrorCategory.TIMEOUT, f"{prefix}_TIMEOUT", None),
    }
    item = mapped.get(status_code)
    if item is not None:
        category, stable_code, retryable = item
        return AIAdapterError(category, stable_code=stable_code, retryable=retryable)
    if status_code >= 500:
        return AIAdapterError(
            AIAdapterErrorCategory.TEMPORARY_PROVIDER_FAILURE,
            stable_code=f"{prefix}_TEMPORARY_PROVIDER_FAILURE",
        )
    return AIAdapterError(
        AIAdapterErrorCategory.PERMANENT_PROVIDER_FAILURE,
        stable_code=f"{prefix}_REQUEST_REJECTED",
        retryable=False,
    )


class OpenAICompatibleDetectionAdapter:
    spec: OpenAIChatProviderSpec
    descriptor: AIAdapterDescriptor
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
            return self._credential_resolver.resolve(self.spec.provider_key)
        except AICredentialStateConflict:
            raise AIAdapterError(
                AIAdapterErrorCategory.CONFIGURATION_UNAVAILABLE,
                stable_code=f"{self.spec.error_prefix}_CREDENTIAL_UNAVAILABLE",
                retryable=False,
            ) from None
        except AICredentialCryptoFailure:
            raise AIAdapterError(
                AIAdapterErrorCategory.CONFIGURATION_UNAVAILABLE,
                stable_code=f"{self.spec.error_prefix}_CREDENTIAL_CRYPTO_FAILURE",
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
            "temperature": float(payload.temperature),
        }
        if payload.max_output_tokens is not None:
            body["max_tokens"] = payload.max_output_tokens
        return body

    def _validate_request(self, request: AIAdapterRequest[DetectionPayload]) -> None:
        if (
            request.identity != self.descriptor.identity
            or request.capability != AIModelCapability.GEO_DETECTION
            or request.adapter_version != self.descriptor.adapter_version
            or request.prompt_version != self.descriptor.prompt_version
            or not isinstance(request.payload, DetectionPayload)
        ):
            raise AIAdapterError(
                AIAdapterErrorCategory.INVALID_REQUEST,
                stable_code=f"{self.spec.error_prefix}_REQUEST_INVALID",
                retryable=False,
            )

    def _provider_success_guard(self, data: dict[str, object]) -> None:
        del data

    def _provider_model_id(
        self,
        data: dict[str, object],
        request: AIAdapterRequest[DetectionPayload],
    ) -> str | None:
        del request
        return _safe_optional_text(data.get("model"), maximum=255)

    def _provider_request_id(self, data: dict[str, object]) -> str | None:
        return _safe_optional_text(data.get("id"))

    def invoke(
        self, request: AIAdapterRequest[DetectionPayload]
    ) -> AIAdapterResponse[DetectionOutput]:
        self._validate_request(request)
        credential = self._resolve_credential()
        started = monotonic()
        client = httpx.Client(
            base_url=self.spec.base_url,
            follow_redirects=False,
            trust_env=False,
            transport=self._transport,
            timeout=float(request.timeout_seconds),
        )
        try:
            response = client.post(
                self.spec.chat_path,
                headers={
                    "Authorization": f"Bearer {credential.value}",
                    "Content-Type": "application/json",
                },
                json=self._request_body(request.payload),
            )
        except httpx.TimeoutException:
            raise AIAdapterError(
                AIAdapterErrorCategory.TIMEOUT,
                stable_code=f"{self.spec.error_prefix}_TIMEOUT",
            ) from None
        except httpx.NetworkError:
            raise AIAdapterError(
                AIAdapterErrorCategory.NETWORK,
                stable_code=f"{self.spec.error_prefix}_NETWORK",
            ) from None
        except httpx.HTTPError:
            raise AIAdapterError(
                AIAdapterErrorCategory.NETWORK,
                stable_code=f"{self.spec.error_prefix}_HTTP_TRANSPORT",
            ) from None
        finally:
            if self._transport is None:
                client.close()

        latency_ms = max(0, int((monotonic() - started) * 1000))
        if response.status_code != 200:
            raise _http_error(self.spec, response.status_code)
        if len(response.content) > MAX_PROVIDER_RESPONSE_BYTES:
            raise AIAdapterError(
                AIAdapterErrorCategory.RESPONSE_PARSE,
                stable_code=f"{self.spec.error_prefix}_RESPONSE_TOO_LARGE",
                retryable=False,
            )

        try:
            data = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            raise AIAdapterError(
                AIAdapterErrorCategory.RESPONSE_PARSE,
                stable_code=f"{self.spec.error_prefix}_RESPONSE_INVALID",
                retryable=False,
            ) from None
        if not isinstance(data, dict):
            raise AIAdapterError(
                AIAdapterErrorCategory.RESPONSE_PARSE,
                stable_code=f"{self.spec.error_prefix}_RESPONSE_INVALID",
                retryable=False,
            )

        self._provider_success_guard(data)

        choices = data.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise AIAdapterError(
                AIAdapterErrorCategory.RESPONSE_PARSE,
                stable_code=f"{self.spec.error_prefix}_RESPONSE_INVALID",
                retryable=False,
            )
        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, dict):
            raise AIAdapterError(
                AIAdapterErrorCategory.RESPONSE_PARSE,
                stable_code=f"{self.spec.error_prefix}_RESPONSE_INVALID",
                retryable=False,
            )
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise AIAdapterError(
                AIAdapterErrorCategory.RESPONSE_PARSE,
                stable_code=f"{self.spec.error_prefix}_RESPONSE_EMPTY",
                retryable=False,
            )

        usage_data = data.get("usage")
        if not isinstance(usage_data, dict):
            raise AIAdapterError(
                AIAdapterErrorCategory.RESPONSE_PARSE,
                stable_code=f"{self.spec.error_prefix}_USAGE_INVALID",
                retryable=False,
            )
        input_tokens = _int(usage_data.get("prompt_tokens"))
        output_tokens = _int(usage_data.get("completion_tokens"))
        total_tokens = _int(usage_data.get("total_tokens"))
        if input_tokens is None or output_tokens is None or total_tokens is None:
            raise AIAdapterError(
                AIAdapterErrorCategory.RESPONSE_PARSE,
                stable_code=f"{self.spec.error_prefix}_USAGE_INVALID",
                retryable=False,
            )

        provider_model_id = self._provider_model_id(data, request)
        if provider_model_id is None:
            raise AIAdapterError(
                AIAdapterErrorCategory.RESPONSE_PARSE,
                stable_code=f"{self.spec.error_prefix}_MODEL_ID_INVALID",
                retryable=False,
            )

        metadata: dict[str, object] = {"provider_model_id": provider_model_id}
        system_fingerprint = _safe_optional_text(data.get("system_fingerprint"))
        if system_fingerprint is not None:
            metadata["system_fingerprint"] = system_fingerprint

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
                stable_code=f"{self.spec.error_prefix}_RESPONSE_INVALID",
                retryable=False,
            ) from None

        return AIAdapterResponse(
            request_id=request.request_id,
            identity=self.descriptor.identity,
            output=output,
            provider_request_id=self._provider_request_id(data),
            usage=AIUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
            ),
            timing=AIAdapterTiming(latency_ms=latency_ms),
            finish_reason=_finish_reason(choice.get("finish_reason")),
            sanitized_provider_metadata=metadata,
        )
