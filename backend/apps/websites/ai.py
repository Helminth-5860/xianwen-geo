from __future__ import annotations

from apps.ai.adapters.deepseek_content import DeepSeekStructuredContentAdapter
from apps.ai.contracts import AIAdapterDescriptor, AIModelCapability, AIModelIdentity

WEBSITE_ADAPTER_VERSION = "deepseek-website-v1"
WEBSITE_PROMPT_VERSION = "geo-website-v1"

WEBSITE_DESCRIPTOR = AIAdapterDescriptor(
    identity=AIModelIdentity(provider_key="deepseek", model_key="deepseek"),
    capabilities=frozenset({AIModelCapability.TEXT_GENERATION}),
    adapter_version=WEBSITE_ADAPTER_VERSION,
    prompt_version=WEBSITE_PROMPT_VERSION,
)


class DeepSeekWebsiteAdapter(DeepSeekStructuredContentAdapter):
    """Website-specific structured-content adapter using the existing hardened transport."""

    descriptor = WEBSITE_DESCRIPTOR
