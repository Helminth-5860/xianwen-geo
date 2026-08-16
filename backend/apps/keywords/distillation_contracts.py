from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class DistillationKeywordInput:
    id: str
    text: str
    structure_type: str
    is_regional: bool
    region_level: str
    region_text: str
    region_matching_key: str
    business_category: str | None
    search_intent: str | None
    relevance_score: int | None
    priority: str | None


@dataclass(frozen=True)
class DistillationRequest:
    job_id: str
    subject_id: str
    subject_version_id: str
    keyword_set_version_id: str
    subject_values: dict[str, Any]
    keywords: tuple[DistillationKeywordInput, ...]


@dataclass(frozen=True)
class DistilledKeyword:
    source_keyword_id: str
    action: str
    canonical_keyword_id: str | None
    merge_group_key: str | None
    reason: str


@dataclass(frozen=True)
class DistillationResponse:
    items: tuple[DistilledKeyword, ...]
    model_key: str
    provider_metrics: dict[str, Any]


class DistillationProvider(Protocol):
    key: str
    model_key: str
    adapter_version: str
    prompt_version: str

    def distill(self, request: DistillationRequest) -> DistillationResponse: ...
