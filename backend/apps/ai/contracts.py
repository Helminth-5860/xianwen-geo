from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

STABLE_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")


class AIModelCapability(StrEnum):
    SUBJECT_ENRICHMENT = "subject_enrichment"
    KEYWORD_GENERATION = "keyword_generation"
    KEYWORD_DISTILLATION = "keyword_distillation"
    QUESTION_GENERATION = "question_generation"
    GEO_DETECTION = "geo_detection"
    TEXT_GENERATION = "text_generation"
    IMAGE_GENERATION = "image_generation"
    SEMANTIC_SCORING = "semantic_scoring"
    IMPROVEMENT_STRATEGY = "improvement_strategy"
    SUBJECT_ASSISTANT = "subject_assistant"


class AIFinishReason(StrEnum):
    STOP = "stop"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"
    TOOL_CALL = "tool_call"
    UNKNOWN = "unknown"


def _validate_stable_key(value: str, field_name: str) -> None:
    if not STABLE_KEY_PATTERN.fullmatch(value):
        raise ValueError(f"{field_name} must be a stable machine key.")


@dataclass(frozen=True)
class AIModelIdentity:
    provider_key: str
    model_key: str

    def __post_init__(self) -> None:
        _validate_stable_key(self.provider_key, "provider_key")
        _validate_stable_key(self.model_key, "model_key")


@dataclass(frozen=True)
class AIAdapterDescriptor:
    identity: AIModelIdentity
    capabilities: frozenset[AIModelCapability]
    adapter_version: str
    prompt_version: str
    is_mock: bool = False
    is_available: bool = True

    def __post_init__(self) -> None:
        if not self.capabilities:
            raise ValueError("capabilities must not be empty.")
        _validate_stable_key(self.adapter_version, "adapter_version")
        _validate_stable_key(self.prompt_version, "prompt_version")
        if self.is_mock and not self.is_available:
            raise ValueError("A mock adapter must be available when registered.")


@dataclass(frozen=True)
class AIAdapterRequest[PayloadT]:
    request_id: str
    correlation_id: str | None
    identity: AIModelIdentity
    capability: AIModelCapability
    adapter_version: str
    prompt_version: str
    timeout_seconds: int
    payload: PayloadT = field(repr=False)
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not self.request_id or len(self.request_id) > 128:
            raise ValueError("request_id must contain at most 128 characters.")
        if self.correlation_id is not None and (
            not self.correlation_id or len(self.correlation_id) > 128
        ):
            raise ValueError("correlation_id must contain at most 128 characters.")
        _validate_stable_key(self.adapter_version, "adapter_version")
        _validate_stable_key(self.prompt_version, "prompt_version")
        if type(self.timeout_seconds) is not int or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be a positive integer.")


@dataclass(frozen=True)
class AIUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    request_count: int = 1

    def __post_init__(self) -> None:
        for name in ("input_tokens", "output_tokens", "total_tokens"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be a non-negative integer or null.")
        if type(self.request_count) is not int or self.request_count < 1:
            raise ValueError("request_count must be a positive integer.")


@dataclass(frozen=True)
class AIAdapterTiming:
    latency_ms: int

    def __post_init__(self) -> None:
        if type(self.latency_ms) is not int or self.latency_ms < 0:
            raise ValueError("latency_ms must be a non-negative integer.")


@dataclass(frozen=True)
class AIAdapterResponse[OutputT]:
    request_id: str
    identity: AIModelIdentity
    output: OutputT = field(repr=False)
    provider_request_id: str | None = None
    usage: AIUsage = field(default_factory=AIUsage)
    timing: AIAdapterTiming = field(default_factory=lambda: AIAdapterTiming(latency_ms=0))
    finish_reason: AIFinishReason = AIFinishReason.UNKNOWN
    sanitized_provider_metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not self.request_id or len(self.request_id) > 128:
            raise ValueError("request_id must contain at most 128 characters.")
        if self.provider_request_id is not None and (
            not self.provider_request_id
            or len(self.provider_request_id) > 128
            or any(ord(character) < 32 for character in self.provider_request_id)
        ):
            raise ValueError("provider_request_id is invalid.")
        from .sanitization import sanitize_provider_payload

        sanitized = sanitize_provider_payload(self.sanitized_provider_metadata)
        object.__setattr__(
            self,
            "sanitized_provider_metadata",
            sanitized if isinstance(sanitized, dict) else {},
        )


class AIAdapter[PayloadT, OutputT](Protocol):
    descriptor: AIAdapterDescriptor

    def invoke(self, request: AIAdapterRequest[PayloadT]) -> AIAdapterResponse[OutputT]: ...


@dataclass(frozen=True)
class AdapterCredential:
    """A non-persisting credential injection value for future real adapters."""

    value: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("Credential value must not be empty.")


class CredentialResolver(Protocol):
    def resolve(self, provider_key: str) -> AdapterCredential: ...
