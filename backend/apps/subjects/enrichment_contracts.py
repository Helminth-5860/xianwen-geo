from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class UntrustedSource:
    source_id: str
    source_type: str
    content_digest: str
    text: str


@dataclass(frozen=True)
class TargetField:
    field_key: str
    field_type: str
    label: str
    current_value: Any
    options: tuple[str, ...]


@dataclass(frozen=True)
class SubjectEnrichmentRequest:
    job_id: str
    subject_id: str
    subject_values: dict[str, Any]
    sources: tuple[UntrustedSource, ...]
    target_fields: tuple[TargetField, ...]


@dataclass(frozen=True)
class FieldSuggestion:
    field_key: str
    value: Any
    confidence: str
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class SubjectEnrichmentResponse:
    suggestions: tuple[FieldSuggestion, ...]
    model_key: str
    provider_metrics: dict[str, Any]


class SubjectEnrichmentProvider(Protocol):
    key: str
    model_key: str
    adapter_version: str
    prompt_version: str

    def enrich(self, request: SubjectEnrichmentRequest) -> SubjectEnrichmentResponse: ...
