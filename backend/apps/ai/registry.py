from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .contracts import AIAdapterDescriptor, AIModelCapability
from .errors import AIAdapterError, AIAdapterErrorCategory

AdapterFactory = Callable[[], Any]
RegistryKey = tuple[str, str, AIModelCapability]


class AIModelRegistry:
    """In-process adapter metadata/lookup registry; runtime DB config belongs to XW-0402."""

    def __init__(self) -> None:
        self._entries: dict[RegistryKey, tuple[AIAdapterDescriptor, AdapterFactory]] = {}

    def register(self, descriptor: AIAdapterDescriptor, factory: AdapterFactory) -> None:
        for capability in descriptor.capabilities:
            key = (
                descriptor.identity.provider_key,
                descriptor.identity.model_key,
                capability,
            )
            if key in self._entries:
                raise AIAdapterError(
                    AIAdapterErrorCategory.CONFIGURATION_UNAVAILABLE,
                    stable_code="AI_REGISTRY_DUPLICATE",
                    retryable=False,
                )
            self._entries[key] = (descriptor, factory)

    def resolve(
        self,
        *,
        provider_key: str,
        model_key: str,
        capability: AIModelCapability,
    ) -> Any:
        key = (provider_key, model_key, capability)
        entry = self._entries.get(key)
        if entry is not None:
            return entry[1]()

        provider_entries = [
            registered for registered in self._entries if registered[0] == provider_key
        ]
        if not provider_entries:
            raise AIAdapterError(AIAdapterErrorCategory.UNKNOWN_PROVIDER, retryable=False)
        model_entries = [
            registered for registered in provider_entries if registered[1] == model_key
        ]
        if not model_entries:
            raise AIAdapterError(AIAdapterErrorCategory.UNKNOWN_MODEL, retryable=False)
        raise AIAdapterError(AIAdapterErrorCategory.UNSUPPORTED_CAPABILITY, retryable=False)

    def resolve_provider(self, *, provider_key: str, capability: AIModelCapability) -> Any:
        matches = [
            entry
            for key, entry in self._entries.items()
            if key[0] == provider_key and key[2] == capability
        ]
        if not matches:
            providers = {key[0] for key in self._entries}
            category = (
                AIAdapterErrorCategory.UNSUPPORTED_CAPABILITY
                if provider_key in providers
                else AIAdapterErrorCategory.UNKNOWN_PROVIDER
            )
            raise AIAdapterError(category, retryable=False)
        if len(matches) != 1:
            raise AIAdapterError(
                AIAdapterErrorCategory.CONFIGURATION_UNAVAILABLE,
                stable_code="AI_REGISTRY_AMBIGUOUS",
                retryable=False,
            )
        return matches[0][1]()

    def descriptors(self) -> tuple[AIAdapterDescriptor, ...]:
        unique = {id(entry[0]): entry[0] for entry in self._entries.values()}
        return tuple(
            sorted(
                unique.values(),
                key=lambda item: (
                    item.identity.provider_key,
                    item.identity.model_key,
                    sorted(item.capabilities),
                ),
            )
        )


model_registry = AIModelRegistry()
