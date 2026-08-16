from __future__ import annotations

import re
from enum import StrEnum


class AIAdapterErrorCategory(StrEnum):
    CONFIGURATION_UNAVAILABLE = "configuration_unavailable"
    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    QUOTA_EXHAUSTED = "quota_exhausted"
    NETWORK = "network"
    TEMPORARY_PROVIDER_FAILURE = "temporary_provider_failure"
    PERMANENT_PROVIDER_FAILURE = "permanent_provider_failure"
    INVALID_REQUEST = "invalid_request"
    CONTENT_POLICY = "content_policy"
    MODEL_UNAVAILABLE = "model_unavailable"
    PROVIDER_INTERNAL = "provider_internal"
    RESPONSE_PARSE = "response_parse"
    UNKNOWN_PROVIDER = "unknown_provider"
    UNKNOWN_MODEL = "unknown_model"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    INTERNAL_ADAPTER = "internal_adapter"


RETRYABLE_CATEGORIES = frozenset(
    {
        AIAdapterErrorCategory.TIMEOUT,
        AIAdapterErrorCategory.RATE_LIMIT,
        AIAdapterErrorCategory.NETWORK,
        AIAdapterErrorCategory.TEMPORARY_PROVIDER_FAILURE,
        AIAdapterErrorCategory.MODEL_UNAVAILABLE,
        AIAdapterErrorCategory.PROVIDER_INTERNAL,
    }
)
CONFIGURATION_CATEGORIES = frozenset(
    {
        AIAdapterErrorCategory.CONFIGURATION_UNAVAILABLE,
        AIAdapterErrorCategory.UNKNOWN_PROVIDER,
        AIAdapterErrorCategory.UNKNOWN_MODEL,
        AIAdapterErrorCategory.UNSUPPORTED_CAPABILITY,
    }
)
PROVIDER_CATEGORIES = frozenset(
    {
        AIAdapterErrorCategory.AUTHENTICATION,
        AIAdapterErrorCategory.PERMISSION,
        AIAdapterErrorCategory.TIMEOUT,
        AIAdapterErrorCategory.RATE_LIMIT,
        AIAdapterErrorCategory.QUOTA_EXHAUSTED,
        AIAdapterErrorCategory.NETWORK,
        AIAdapterErrorCategory.TEMPORARY_PROVIDER_FAILURE,
        AIAdapterErrorCategory.PERMANENT_PROVIDER_FAILURE,
        AIAdapterErrorCategory.CONTENT_POLICY,
        AIAdapterErrorCategory.MODEL_UNAVAILABLE,
        AIAdapterErrorCategory.PROVIDER_INTERNAL,
    }
)

SAFE_MESSAGES = {
    AIAdapterErrorCategory.CONFIGURATION_UNAVAILABLE: "AI adapter is not configured.",
    AIAdapterErrorCategory.AUTHENTICATION: "AI provider authentication failed.",
    AIAdapterErrorCategory.PERMISSION: "AI provider permission was denied.",
    AIAdapterErrorCategory.TIMEOUT: "AI provider request timed out.",
    AIAdapterErrorCategory.RATE_LIMIT: "AI provider rate limit was reached.",
    AIAdapterErrorCategory.QUOTA_EXHAUSTED: "AI provider quota is unavailable.",
    AIAdapterErrorCategory.NETWORK: "AI provider network request failed.",
    AIAdapterErrorCategory.TEMPORARY_PROVIDER_FAILURE: "AI provider is temporarily unavailable.",
    AIAdapterErrorCategory.PERMANENT_PROVIDER_FAILURE: "AI provider rejected the request.",
    AIAdapterErrorCategory.INVALID_REQUEST: "AI adapter request is invalid.",
    AIAdapterErrorCategory.CONTENT_POLICY: "AI provider content policy rejected the request.",
    AIAdapterErrorCategory.MODEL_UNAVAILABLE: "AI model is unavailable.",
    AIAdapterErrorCategory.PROVIDER_INTERNAL: "AI provider returned an internal error.",
    AIAdapterErrorCategory.RESPONSE_PARSE: "AI provider response is invalid.",
    AIAdapterErrorCategory.UNKNOWN_PROVIDER: "AI provider is not registered.",
    AIAdapterErrorCategory.UNKNOWN_MODEL: "AI model is not registered.",
    AIAdapterErrorCategory.UNSUPPORTED_CAPABILITY: "AI model capability is not supported.",
    AIAdapterErrorCategory.INTERNAL_ADAPTER: "AI adapter failed internally.",
}


class AIAdapterError(Exception):
    def __init__(
        self,
        category: AIAdapterErrorCategory,
        *,
        stable_code: str | None = None,
        retryable: bool | None = None,
    ) -> None:
        self.category = category
        default_code = f"AI_{category.value.upper()}"
        self.stable_code = (
            stable_code
            if stable_code is not None and re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", stable_code)
            else default_code
        )
        self.retryable = category in RETRYABLE_CATEGORIES if retryable is None else retryable
        super().__init__(SAFE_MESSAGES[category])

    @property
    def configuration_failure(self) -> bool:
        return self.category in CONFIGURATION_CATEGORIES

    @property
    def provider_failure(self) -> bool:
        return self.category in PROVIDER_CATEGORIES

    @property
    def schema_failure(self) -> bool:
        return self.category == AIAdapterErrorCategory.RESPONSE_PARSE

    def __repr__(self) -> str:
        return (
            f"AIAdapterError(category={self.category.value!r}, "
            f"stable_code={self.stable_code!r}, retryable={self.retryable!r})"
        )


DOMAIN_ERROR_SUFFIXES = {
    AIAdapterErrorCategory.TIMEOUT: "TIMEOUT",
    AIAdapterErrorCategory.RATE_LIMIT: "RATE_LIMITED",
    AIAdapterErrorCategory.NETWORK: "TEMPORARY",
    AIAdapterErrorCategory.TEMPORARY_PROVIDER_FAILURE: "TEMPORARY",
    AIAdapterErrorCategory.MODEL_UNAVAILABLE: "TEMPORARY",
    AIAdapterErrorCategory.PROVIDER_INTERNAL: "TEMPORARY",
}


def domain_provider_error_code(error: AIAdapterError, prefix: str) -> str:
    suffix = DOMAIN_ERROR_SUFFIXES.get(error.category, "REJECTED")
    return f"{prefix}_{suffix}"
