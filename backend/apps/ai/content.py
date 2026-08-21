from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StructuredContentPayload:
    provider_model_id: str
    system_prompt: str
    user_payload: dict[str, Any]
    max_output_tokens: int
    temperature: float

    def __post_init__(self) -> None:
        if not self.provider_model_id or len(self.provider_model_id) > 255:
            raise ValueError("provider_model_id is invalid")
        if not self.system_prompt or len(self.system_prompt) > 20_000:
            raise ValueError("system_prompt is invalid")
        if not 1 <= self.max_output_tokens <= 16_000:
            raise ValueError("max_output_tokens is invalid")
        if not 0 <= self.temperature <= 2:
            raise ValueError("temperature is invalid")


@dataclass(frozen=True)
class StructuredContentOutput:
    content: dict[str, Any]
