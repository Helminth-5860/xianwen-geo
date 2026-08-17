from __future__ import annotations

from dataclasses import replace

from django.conf import settings

from apps.ai.contracts import (
    AIAdapterDescriptor,
    AIAdapterRequest,
    AIAdapterResponse,
    AIModelCapability,
    AIModelIdentity,
)
from apps.ai.errors import AIAdapterError, AIAdapterErrorCategory, domain_provider_error_code
from apps.ai.mock import DeterministicMockAIAdapter
from apps.ai.registry import model_registry

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


class MockSubjectEnrichmentProvider(
    DeterministicMockAIAdapter[SubjectEnrichmentRequest, SubjectEnrichmentResponse]
):
    descriptor = AIAdapterDescriptor(
        identity=AIModelIdentity(
            provider_key="mock",
            model_key="mock-subject-enrichment-v1",
        ),
        capabilities=frozenset({AIModelCapability.SUBJECT_ENRICHMENT}),
        adapter_version="1",
        prompt_version="subject-enrichment-v1",
        is_mock=True,
    )
    key = descriptor.identity.provider_key
    model_key = descriptor.identity.model_key
    adapter_version = descriptor.adapter_version
    prompt_version = descriptor.prompt_version

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

    def _scenario(self) -> str:
        return getattr(settings, "SUBJECT_ENRICHMENT_MOCK_SCENARIO", "success")

    def _build_output(
        self,
        request: SubjectEnrichmentRequest,
        scenario: str,
    ) -> SubjectEnrichmentResponse:
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

    def enrich(self, request: SubjectEnrichmentRequest) -> SubjectEnrichmentResponse:
        normalized = self.normalized_request(
            request,
            request_id=request.job_id,
            timeout_seconds=settings.SUBJECT_ENRICHMENT_PROVIDER_TIMEOUT_SECONDS,
        )
        try:
            response = self.invoke(normalized)
        except AIAdapterError as exc:
            raise SubjectEnrichmentProviderError(
                domain_provider_error_code(exc, "SUBJECT_ENRICHMENT_PROVIDER"),
                permanent=not exc.retryable,
            ) from None
        return replace(
            response.output,
            provider_metrics=dict(response.sanitized_provider_metadata),
        )


class UnavailableSubjectEnrichmentProvider:
    descriptor = AIAdapterDescriptor(
        identity=AIModelIdentity(provider_key="unavailable", model_key="unavailable"),
        capabilities=frozenset({AIModelCapability.SUBJECT_ENRICHMENT}),
        adapter_version="1",
        prompt_version="subject-enrichment-v1",
        is_available=False,
    )
    key = descriptor.identity.provider_key
    model_key = descriptor.identity.model_key
    adapter_version = descriptor.adapter_version
    prompt_version = descriptor.prompt_version

    def invoke(
        self,
        request: AIAdapterRequest[SubjectEnrichmentRequest],
    ) -> AIAdapterResponse[SubjectEnrichmentResponse]:
        raise AIAdapterError(AIAdapterErrorCategory.CONFIGURATION_UNAVAILABLE, retryable=False)

    def enrich(self, request: SubjectEnrichmentRequest) -> SubjectEnrichmentResponse:
        raise SubjectEnrichmentProviderUnavailable


model_registry.register(MockSubjectEnrichmentProvider.descriptor, MockSubjectEnrichmentProvider)
model_registry.register(
    UnavailableSubjectEnrichmentProvider.descriptor,
    UnavailableSubjectEnrichmentProvider,
)


def get_subject_enrichment_provider(provider_key: str | None = None):
    provider = provider_key or settings.SUBJECT_ENRICHMENT_PROVIDER
    try:
        return model_registry.resolve_provider(
            provider_key=provider,
            capability=AIModelCapability.SUBJECT_ENRICHMENT,
        )
    except AIAdapterError:
        raise SubjectEnrichmentProviderUnavailable from None


def require_available_subject_enrichment_provider():
    provider = get_subject_enrichment_provider()
    if not provider.descriptor.is_available:
        raise SubjectEnrichmentProviderUnavailable
    return provider
