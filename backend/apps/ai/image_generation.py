from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ImageGenerationPayload:
    provider_model_id: str
    prompt: str
    reference_image: str | None = None
    size: str | None = None
    output_format: str | None = "png"

    def __post_init__(self) -> None:
        if not self.provider_model_id or len(self.provider_model_id) > 255:
            raise ValueError("provider_model_id is invalid")
        if not self.prompt.strip() or len(self.prompt) > 4000:
            raise ValueError("prompt is invalid")
        if self.reference_image is not None and not (
            self.reference_image.startswith("https://")
            or self.reference_image.startswith("data:image/")
        ):
            raise ValueError("reference_image is invalid")
        if self.size is not None and (not self.size or len(self.size) > 64):
            raise ValueError("size is invalid")
        if self.output_format not in {None, "png", "jpeg"}:
            raise ValueError("output_format is invalid")


@dataclass(frozen=True)
class ImageGenerationArtifact:
    url: str | None
    b64_json: str | None
    size: str | None

    def __post_init__(self) -> None:
        if (self.url is None) == (self.b64_json is None):
            raise ValueError("exactly one image result transport is required")


@dataclass(frozen=True)
class ImageGenerationOutput:
    provider_model_id: str
    created: int | None
    artifacts: tuple[ImageGenerationArtifact, ...]
    image_count: int
    provider_usage: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        if not self.provider_model_id or len(self.provider_model_id) > 255:
            raise ValueError("provider_model_id is invalid")
        if not self.artifacts or self.image_count != len(self.artifacts):
            raise ValueError("image generation output is empty")
        if any(
            not key or type(value) is not int or value < 0 for key, value in self.provider_usage
        ):
            raise ValueError("image generation usage is invalid")
