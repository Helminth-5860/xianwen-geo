from __future__ import annotations

from django.conf import settings

from .enrichment_contracts import (
    FieldSuggestion,
    SubjectEnrichmentRequest,
    SubjectEnrichmentResponse,
)
from .enrichment_exceptions import (
    SubjectEnrichmentInvalidResponse,
    SubjectEnrichmentProviderError,
    SubjectEnrichmentProviderUnavailable,
)


class MockSubjectEnrichmentProvider:
    key = "mock"
    model_key = "mock-subject-enrichment-v1"
    adapter_version = "1"
    prompt_version = "subject-enrichment-v1"

    def _value(self, field):
        if field.field_type == "textarea":
            return f"Mock AI 建议：{field.label}"[:1000]
        if field.field_type == "text":
            return f"Mock AI 建议：{field.label}"[:500]
        if field.field_type == "number":
            return 1
        if field.field_type == "date":
            return "2026-01-01"
        if field.field_type == "url":
            current = field.current_value
            return current if isinstance(current, str) and current else "https://example.com"
        if field.field_type in {"single", "select"}:
            if not field.options:
                raise SubjectEnrichmentInvalidResponse
            return field.options[0]
        if field.field_type == "multi":
            return list(field.options[:1])
        raise SubjectEnrichmentInvalidResponse

    def enrich(self, request: SubjectEnrichmentRequest) -> SubjectEnrichmentResponse:
        scenario = getattr(settings, "SUBJECT_ENRICHMENT_MOCK_SCENARIO", "success")
        if scenario == "timeout":
            raise SubjectEnrichmentProviderError(
                "SUBJECT_ENRICHMENT_PROVIDER_TIMEOUT", permanent=False
            )
        if scenario == "rate_limit":
            raise SubjectEnrichmentProviderError(
                "SUBJECT_ENRICHMENT_PROVIDER_RATE_LIMITED", permanent=False
            )
        if scenario == "temporary":
            raise SubjectEnrichmentProviderError(
                "SUBJECT_ENRICHMENT_PROVIDER_TEMPORARY", permanent=False
            )
        if scenario == "permanent":
            raise SubjectEnrichmentProviderError(
                "SUBJECT_ENRICHMENT_PROVIDER_REJECTED", permanent=True
            )
        if scenario == "invalid_response":
            return SubjectEnrichmentResponse(
                suggestions=(
                    FieldSuggestion(
                        field_key="__unknown__",
                        value="invalid",
                        confidence="high",
                        source_ids=(),
                    ),
                ),
                model_key=self.model_key,
                provider_metrics={},
            )

        source_ids = tuple(source.source_id for source in request.sources[:1])
        suggestions = []
        for index, field in enumerate(request.target_fields):
            confidence = (
                "low" if scenario == "low_confidence" else ("high" if index == 0 else "medium")
            )
            suggestions.append(
                FieldSuggestion(
                    field_key=field.field_key,
                    value=self._value(field),
                    confidence=confidence,
                    source_ids=source_ids,
                )
            )
        return SubjectEnrichmentResponse(
            suggestions=tuple(suggestions),
            model_key=self.model_key,
            provider_metrics={"mock": True, "source_count": len(request.sources)},
        )


class UnavailableSubjectEnrichmentProvider:
    key = "unavailable"
    model_key = "unavailable"
    adapter_version = "1"
    prompt_version = "subject-enrichment-v1"

    def enrich(self, request: SubjectEnrichmentRequest) -> SubjectEnrichmentResponse:
        raise SubjectEnrichmentProviderUnavailable


def get_subject_enrichment_provider(provider_key: str | None = None):
    provider = provider_key or settings.SUBJECT_ENRICHMENT_PROVIDER
    if provider == "mock":
        return MockSubjectEnrichmentProvider()
    if provider == "unavailable":
        return UnavailableSubjectEnrichmentProvider()
    raise SubjectEnrichmentProviderUnavailable


def require_available_subject_enrichment_provider():
    provider = get_subject_enrichment_provider()
    if provider.key == "unavailable":
        raise SubjectEnrichmentProviderUnavailable
    return provider
