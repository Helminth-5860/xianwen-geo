from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class KeywordGenerationRequest:
    job_id: str
    subject_id: str
    subject_version_id: str
    subject_values: dict[str, Any]
    target_count: int
    include_short: bool
    include_long_tail: bool
    include_regional: bool
    regions: tuple[str, ...]
    historical_exclusions: tuple[str, ...]


@dataclass(frozen=True)
class GeneratedKeyword:
    text: str
    structure_type: str
    is_regional: bool
    region_level: str | None
    region_text: str | None
    base_keyword: str | None
    business_category: str
    search_intent: str
    relevance_score: int
    priority: str
    ai_reason: str


@dataclass(frozen=True)
class KeywordGenerationResponse:
    items: tuple[GeneratedKeyword, ...]
    model_key: str
    provider_metrics: dict[str, Any]


class KeywordGenerationProvider(Protocol):
    key: str
    model_key: str
    adapter_version: str
    prompt_version: str

    def generate(self, request: KeywordGenerationRequest) -> KeywordGenerationResponse: ...
