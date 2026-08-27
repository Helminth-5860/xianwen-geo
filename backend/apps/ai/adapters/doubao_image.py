from __future__ import annotations

import json
from time import monotonic

import httpx

from apps.ai.contracts import (
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
from apps.ai.credentials import CapabilityDatabaseCredentialResolver
from apps.ai.errors import AIAdapterError, AIAdapterErrorCategory
from apps.ai.exceptions import AICredentialCryptoFailure, AICredentialStateConflict
from apps.ai.image_generation import (
    ImageGenerationArtifact,
    ImageGenerationOutput,
    ImageGenerationPayload,
)
from apps.ai.registry import AIModelRegistry, model_registry

DOUBAO_IMAGE_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DOUBAO_IMAGE_PATH = "/images/generations"
DOUBAO_IMAGE_API_VERSION = "2024-01-01"
DOUBAO_IMAGE_ADAPTER_VERSION = "doubao-image-generations-v1"
DOUBAO_IMAGE_PROMPT_VERSION = "geo-image-generation-v1"
MAX_PROVIDER_RESPONSE_BYTES = 2_000_000
RESPONSE_MODEL_ALIASES: dict[str, frozenset[str]] = {
    "doubao-seedream-5-0-lite-260128": frozenset(
        {
            "doubao-seedream-5-0-lite-260128",
            "doubao-seedream-5-0-260128",
        }
    ),
}


def _response_model_matches(requested: str, returned: str) -> bool:
    if returned == requested:
        return True
    return returned in RESPONSE_MODEL_ALIASES.get(requested, frozenset())


DOUBAO_IMAGE_DESCRIPTOR = AIAdapterDescriptor(
    identity=AIModelIdentity(provider_key="doubao", model_key="doubao"),
    capabilities=frozenset({AIModelCapability.IMAGE_GENERATION}),
    adapter_version=DOUBAO_IMAGE_ADAPTER_VERSION,
    prompt_version=DOUBAO_IMAGE_PROMPT_VERSION,
)

SENSITIVE_CODES = {
    "InputTextSensitiveContentDetected": "IMAGE_INPUT_TEXT_SENSITIVE",
    "InputImageSensitiveContentDetected": "IMAGE_INPUT_REFERENCE_SENSITIVE",
    "OutputImageSensitiveContentDetected": "IMAGE_OUTPUT_SENSITIVE",
}


def _provider_error(status_code: int, body: object) -> AIAdapterError:
    code = ""
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        value = body["error"].get("code")
        code = value if isinstance(value, str) else ""
    if code in SENSITIVE_CODES:
        return AIAdapterError(
            AIAdapterErrorCategory.PERMANENT_PROVIDER_FAILURE,
            stable_code=SENSITIVE_CODES[code],
            retryable=False,
        )
    if code == "QuotaExceeded":
        return AIAdapterError(
            AIAdapterErrorCategory.QUOTA_EXHAUSTED,
            stable_code="IMAGE_PROVIDER_QUOTA_EXCEEDED",
            retryable=True,
        )
    if status_code == 429:
        return AIAdapterError(
            AIAdapterErrorCategory.RATE_LIMIT,
            stable_code="IMAGE_PROVIDER_RATE_LIMIT",
            retryable=True,
        )
    if status_code in {408, 500, 502, 503, 504}:
        return AIAdapterError(
            AIAdapterErrorCategory.TEMPORARY_PROVIDER_FAILURE,
            stable_code="IMAGE_PROVIDER_TEMPORARY_FAILURE",
            retryable=True,
        )
    if status_code in {401, 403}:
        return AIAdapterError(
            AIAdapterErrorCategory.AUTHENTICATION,
            stable_code="IMAGE_PROVIDER_AUTHENTICATION_FAILED",
            retryable=False,
        )
    return AIAdapterError(
        AIAdapterErrorCategory.PERMANENT_PROVIDER_FAILURE,
        stable_code="IMAGE_PROVIDER_REQUEST_REJECTED",
        retryable=False,
    )


class DoubaoImageGenerationAdapter:
    descriptor = DOUBAO_IMAGE_DESCRIPTOR

    def __init__(
        self,
        *,
        credential_resolver: CredentialResolver | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._credential_resolver = credential_resolver or CapabilityDatabaseCredentialResolver(
            capability=AIModelCapability.IMAGE_GENERATION
        )
        self._transport = transport

    def _credential(self):
        try:
            return self._credential_resolver.resolve("doubao")
        except AICredentialStateConflict:
            raise AIAdapterError(
                AIAdapterErrorCategory.CONFIGURATION_UNAVAILABLE,
                stable_code="IMAGE_CREDENTIAL_BINDING_UNAVAILABLE",
                retryable=False,
            ) from None
        except AICredentialCryptoFailure:
            raise AIAdapterError(
                AIAdapterErrorCategory.CONFIGURATION_UNAVAILABLE,
                stable_code="IMAGE_CREDENTIAL_DECRYPTION_FAILED",
                retryable=False,
            ) from None

    def invoke(
        self, request: AIAdapterRequest[ImageGenerationPayload]
    ) -> AIAdapterResponse[ImageGenerationOutput]:
        if (
            request.identity != self.descriptor.identity
            or request.capability != AIModelCapability.IMAGE_GENERATION
            or request.adapter_version != self.descriptor.adapter_version
            or request.prompt_version != self.descriptor.prompt_version
            or not isinstance(request.payload, ImageGenerationPayload)
        ):
            raise AIAdapterError(
                AIAdapterErrorCategory.INVALID_REQUEST,
                stable_code="IMAGE_PROVIDER_REQUEST_INVALID",
                retryable=False,
            )
        payload = request.payload
        body: dict[str, object] = {
            "model": payload.provider_model_id,
            "prompt": payload.prompt,
            "stream": False,
            "sequential_image_generation": "disabled",
            "response_format": "url",
            "watermark": True,
        }
        if payload.reference_image is not None:
            body["image"] = payload.reference_image
        if payload.size is not None:
            body["size"] = payload.size
        if payload.output_format is not None:
            body["output_format"] = payload.output_format
        started = monotonic()
        client = httpx.Client(
            base_url=DOUBAO_IMAGE_BASE_URL,
            follow_redirects=False,
            trust_env=False,
            timeout=float(request.timeout_seconds),
            transport=self._transport,
        )
        try:
            try:
                response = client.post(
                    DOUBAO_IMAGE_PATH,
                    headers={
                        "Authorization": f"Bearer {self._credential().value}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
            except httpx.TimeoutException:
                raise AIAdapterError(
                    AIAdapterErrorCategory.TIMEOUT,
                    stable_code="IMAGE_PROVIDER_TIMEOUT",
                    retryable=True,
                ) from None
            except httpx.NetworkError:
                raise AIAdapterError(
                    AIAdapterErrorCategory.NETWORK,
                    stable_code="IMAGE_PROVIDER_NETWORK_FAILURE",
                    retryable=True,
                ) from None
            if len(response.content) > MAX_PROVIDER_RESPONSE_BYTES:
                raise AIAdapterError(
                    AIAdapterErrorCategory.RESPONSE_PARSE,
                    stable_code="IMAGE_PROVIDER_RESPONSE_INVALID",
                    retryable=False,
                )
            try:
                data = response.json()
            except (json.JSONDecodeError, ValueError):
                data = None
            if response.status_code >= 400:
                raise _provider_error(response.status_code, data)
            if not isinstance(data, dict):
                raise AIAdapterError(
                    AIAdapterErrorCategory.RESPONSE_PARSE,
                    stable_code="IMAGE_PROVIDER_RESPONSE_INVALID",
                    retryable=False,
                )
            model = data.get("model")
            created = data.get("created")
            rows = data.get("data")
            usage = data.get("usage")
            if (
                not isinstance(model, str)
                or not model
                or not _response_model_matches(payload.provider_model_id, model)
                or (created is not None and type(created) is not int)
                or not isinstance(rows, list)
                or len(rows) != 1
                or (usage is not None and not isinstance(usage, dict))
            ):
                raise AIAdapterError(
                    AIAdapterErrorCategory.RESPONSE_PARSE,
                    stable_code="IMAGE_PROVIDER_RESPONSE_INVALID",
                    retryable=False,
                )
            artifacts: list[ImageGenerationArtifact] = []
            for row in rows:
                if not isinstance(row, dict):
                    raise AIAdapterError(
                        AIAdapterErrorCategory.RESPONSE_PARSE,
                        stable_code="IMAGE_PROVIDER_RESPONSE_INVALID",
                        retryable=False,
                    )
                url = row.get("url")
                b64_json = row.get("b64_json")
                size = row.get("size")
                if url is not None and (not isinstance(url, str) or not url.startswith("https://")):
                    raise AIAdapterError(
                        AIAdapterErrorCategory.RESPONSE_PARSE,
                        stable_code="IMAGE_PROVIDER_RESPONSE_INVALID",
                        retryable=False,
                    )
                if b64_json is not None and not isinstance(b64_json, str):
                    raise AIAdapterError(
                        AIAdapterErrorCategory.RESPONSE_PARSE,
                        stable_code="IMAGE_PROVIDER_RESPONSE_INVALID",
                        retryable=False,
                    )
                if size is not None and not isinstance(size, str):
                    raise AIAdapterError(
                        AIAdapterErrorCategory.RESPONSE_PARSE,
                        stable_code="IMAGE_PROVIDER_RESPONSE_INVALID",
                        retryable=False,
                    )
                try:
                    artifacts.append(ImageGenerationArtifact(url, b64_json, size))
                except ValueError as exc:
                    raise AIAdapterError(
                        AIAdapterErrorCategory.RESPONSE_PARSE,
                        stable_code="IMAGE_PROVIDER_RESPONSE_INVALID",
                        retryable=False,
                    ) from exc
            request_id = response.headers.get("x-request-id")
            if request_id is not None and (not request_id or len(request_id) > 128):
                request_id = None
            normalized_usage: list[tuple[str, int]] = []
            if isinstance(usage, dict):
                for key in ("generated_images", "output_tokens", "total_tokens"):
                    value = usage.get(key)
                    if value is None:
                        continue
                    if type(value) is not int or value < 0:
                        raise AIAdapterError(
                            AIAdapterErrorCategory.RESPONSE_PARSE,
                            stable_code="IMAGE_PROVIDER_RESPONSE_INVALID",
                            retryable=False,
                        )
                    normalized_usage.append((key, value))
            return AIAdapterResponse(
                request_id=request.request_id,
                identity=self.descriptor.identity,
                provider_request_id=request_id,
                output=ImageGenerationOutput(
                    model,
                    created,
                    tuple(artifacts),
                    len(artifacts),
                    tuple(normalized_usage),
                ),
                usage=AIUsage(request_count=1),
                timing=AIAdapterTiming(latency_ms=max(0, int((monotonic() - started) * 1000))),
                finish_reason=AIFinishReason.STOP,
                sanitized_provider_metadata={
                    "api_version": DOUBAO_IMAGE_API_VERSION,
                    "image_count": len(artifacts),
                },
            )
        finally:
            client.close()


def register_doubao_image_adapter(registry: AIModelRegistry = model_registry) -> None:
    registry.register(DOUBAO_IMAGE_DESCRIPTOR, DoubaoImageGenerationAdapter)
