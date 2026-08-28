from __future__ import annotations

from dataclasses import replace
from typing import Any

from apps.ai.adapters.deepseek_content import DeepSeekStructuredContentAdapter
from apps.ai.content import StructuredContentOutput, StructuredContentPayload
from apps.ai.contracts import (
    AIAdapterDescriptor,
    AIAdapterRequest,
    AIAdapterResponse,
    AIModelCapability,
    AIModelIdentity,
)

WEBSITE_ADAPTER_VERSION = "deepseek-website-v1"
WEBSITE_PROMPT_VERSION = "geo-website-v1"

WEBSITE_DESCRIPTOR = AIAdapterDescriptor(
    identity=AIModelIdentity(provider_key="deepseek", model_key="deepseek"),
    capabilities=frozenset({AIModelCapability.TEXT_GENERATION}),
    adapter_version=WEBSITE_ADAPTER_VERSION,
    prompt_version=WEBSITE_PROMPT_VERSION,
)


def _model_user_payload(value: dict[str, Any]) -> dict[str, Any]:
    """Send only content-planning data to the model.

    Contact phone/name and image filenames are retained by the application for deterministic
    rendering, but are not needed by the model and therefore stay out of the provider request.
    """

    authorized = value.get("authorized_subject")
    if not isinstance(authorized, dict):
        return {"site_style": value.get("site_style", "专业商务"), "authorized_subject": {}}

    safe_authorized: dict[str, Any] = {}
    for key in ("subject", "keywords", "questions"):
        item = authorized.get(key)
        if item is not None:
            safe_authorized[key] = item

    business_profile = authorized.get("business_profile")
    if isinstance(business_profile, dict):
        safe_profile = {
            key: business_profile[key]
            for key in ("brand_name", "primary_business", "business_address")
            if business_profile.get(key) not in (None, "")
        }
        if safe_profile:
            safe_authorized["business_profile"] = safe_profile

    return {
        "site_style": value.get("site_style", "专业商务"),
        "authorized_subject": safe_authorized,
    }


class DeepSeekWebsiteAdapter(DeepSeekStructuredContentAdapter):
    """Website-specific structured-content adapter using the existing hardened transport."""

    descriptor = WEBSITE_DESCRIPTOR

    def invoke(
        self,
        request: AIAdapterRequest[StructuredContentPayload],
    ) -> AIAdapterResponse[StructuredContentOutput]:
        payload = replace(
            request.payload,
            user_payload=_model_user_payload(request.payload.user_payload),
        )
        return super().invoke(replace(request, payload=payload))
