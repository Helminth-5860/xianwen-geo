from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

PROVIDER_MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")
MAX_SYSTEM_PROMPT_CHARACTERS = 20_000
MAX_USER_QUESTION_CHARACTERS = 10_000
MAX_OUTPUT_TOKENS = 393_216


def _validate_text(value: str, *, field_name: str, maximum: int) -> None:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"{field_name} is invalid.")
    if "\x00" in value or any(
        unicodedata.category(character) in {"Cc", "Cf"} and character not in {"\n", "\r", "\t"}
        for character in value
    ):
        raise ValueError(f"{field_name} contains forbidden control characters.")


@dataclass(frozen=True)
class DetectionPayload:
    provider_model_id: str
    system_prompt: str = field(repr=False)
    user_question: str = field(repr=False)
    web_search_requested: bool = False
    temperature: float = 0.2
    max_output_tokens: int | None = None

    def __post_init__(self) -> None:
        if not PROVIDER_MODEL_ID_PATTERN.fullmatch(self.provider_model_id):
            raise ValueError("provider_model_id is invalid.")
        _validate_text(
            self.system_prompt,
            field_name="system_prompt",
            maximum=MAX_SYSTEM_PROMPT_CHARACTERS,
        )
        _validate_text(
            self.user_question,
            field_name="user_question",
            maximum=MAX_USER_QUESTION_CHARACTERS,
        )
        if type(self.web_search_requested) is not bool:
            raise ValueError("web_search_requested must be boolean.")
        if type(self.temperature) not in {int, float} or not 0 <= float(self.temperature) <= 2:
            raise ValueError("temperature must be between 0 and 2.")
        if self.max_output_tokens is not None and (
            type(self.max_output_tokens) is not int
            or not 1 <= self.max_output_tokens <= MAX_OUTPUT_TOKENS
        ):
            raise ValueError("max_output_tokens is invalid.")


@dataclass(frozen=True)
class DetectionCitation:
    title: str | None = None
    url: str | None = None
    source_name: str | None = None
    quoted_text: str | None = field(default=None, repr=False)
    provider_rank: int | None = None


@dataclass(frozen=True)
class DetectionOutput:
    provider_model_id: str
    raw_text: str = field(repr=False)
    citations: tuple[DetectionCitation, ...] = field(default_factory=tuple, repr=False)
    web_search_requested: bool = False
    web_search_used: bool = False
    degraded: bool = False

    def __post_init__(self) -> None:
        if not PROVIDER_MODEL_ID_PATTERN.fullmatch(self.provider_model_id):
            raise ValueError("provider_model_id is invalid.")
        _validate_text(
            self.raw_text,
            field_name="raw_text",
            maximum=2_000_000,
        )
        if type(self.web_search_requested) is not bool:
            raise ValueError("web_search_requested must be boolean.")
        if type(self.web_search_used) is not bool:
            raise ValueError("web_search_used must be boolean.")
        if type(self.degraded) is not bool:
            raise ValueError("degraded must be boolean.")
        if self.web_search_used and not self.web_search_requested:
            raise ValueError("web_search_used requires web_search_requested.")
