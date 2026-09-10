"""Canonical image-generation built-in tool configuration."""

import dataclasses
from collections.abc import Mapping
from typing import Literal

_IMAGE_GENERATION_MODEL_KEY = "model"
_IMAGE_GENERATION_DEFAULT_SENTINELS = frozenset({"provider-default"})


@dataclasses.dataclass(frozen=True)
class MaintainedImageGenerationDefault:
    """Use the provider-maintained image-generation default."""

    type: Literal["maintained_default"] = "maintained_default"


@dataclasses.dataclass(frozen=True)
class ExplicitImageGenerationModel:
    """Use one exact provider image-generation model identifier."""

    model_identifier: str
    type: Literal["explicit"] = "explicit"


ImageGenerationModelConfig = (
    MaintainedImageGenerationDefault | ExplicitImageGenerationModel
)


class InvalidImageGenerationModelConfig(ValueError):
    """Image-generation model configuration is not canonical."""


def decode_image_generation_model_config(
    config: Mapping[str, object],
) -> ImageGenerationModelConfig:
    """Decode maintained-default omission or one exact explicit model pin."""
    if _IMAGE_GENERATION_MODEL_KEY not in config:
        return MaintainedImageGenerationDefault()
    value = config[_IMAGE_GENERATION_MODEL_KEY]
    if not isinstance(value, str):
        raise InvalidImageGenerationModelConfig(
            "Image generation model must be a non-empty model identifier."
        )
    model_identifier = value.strip()
    if not model_identifier or model_identifier in _IMAGE_GENERATION_DEFAULT_SENTINELS:
        raise InvalidImageGenerationModelConfig(
            "Use model-key omission for the maintained image generation default."
        )
    return ExplicitImageGenerationModel(model_identifier=model_identifier)
