"""Image-generation built-in configuration tests."""

import pytest

from azents.core.image_generation_config import (
    ExplicitImageGenerationModel,
    InvalidImageGenerationModelConfig,
    MaintainedImageGenerationDefault,
    decode_image_generation_model_config,
)


def test_missing_model_uses_maintained_default() -> None:
    """Model-key omission selects the maintained provider default."""
    assert decode_image_generation_model_config({"quality": "high"}) == (
        MaintainedImageGenerationDefault()
    )


def test_explicit_model_is_trimmed_without_mutating_other_config() -> None:
    """An explicit provider identifier is decoded independently of other keys."""
    config: dict[str, object] = {
        "model": "  gpt-image-2.5-flare  ",
        "quality": "high",
    }

    assert decode_image_generation_model_config(config) == (
        ExplicitImageGenerationModel(model_identifier="gpt-image-2.5-flare")
    )
    assert config == {
        "model": "  gpt-image-2.5-flare  ",
        "quality": "high",
    }


@pytest.mark.parametrize("value", [None, "", "   ", 1, [], "provider-default"])
def test_invalid_model_values_are_rejected(value: object) -> None:
    """Null, blank, non-string, and UI sentinel values are non-canonical."""
    with pytest.raises(InvalidImageGenerationModelConfig):
        decode_image_generation_model_config({"model": value})
