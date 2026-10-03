"""Current image usability preserves user-safe inference failure mapping."""

from typing import Literal

import pytest

from azents.core.inference_profile import InferenceProfileFailureCode
from azents.services.image_generation_catalog import (
    ImageGenerationRuntimeConfigurationError,
)
from azents.worker.run.executor import _profile_resolution_failure


@pytest.mark.parametrize(
    ("reason", "code"),
    [
        (
            "integration_disabled",
            InferenceProfileFailureCode.IMAGE_INTEGRATION_DISABLED,
        ),
        (
            "explicit_selection_unsupported",
            InferenceProfileFailureCode.IMAGE_EXPLICIT_SELECTION_UNSUPPORTED,
        ),
        ("catalog_unavailable", InferenceProfileFailureCode.IMAGE_CATALOG_UNAVAILABLE),
        ("catalog_unusable", InferenceProfileFailureCode.IMAGE_CATALOG_UNUSABLE),
        ("model_unavailable", InferenceProfileFailureCode.IMAGE_MODEL_UNAVAILABLE),
        (
            "provider_model_mismatch",
            InferenceProfileFailureCode.IMAGE_PROVIDER_MODEL_MISMATCH,
        ),
    ],
)
def test_image_runtime_rejection_maps_to_current_inference_failure(
    reason: Literal[
        "integration_disabled",
        "explicit_selection_unsupported",
        "catalog_unavailable",
        "catalog_unusable",
        "model_unavailable",
        "provider_model_mismatch",
    ],
    code: InferenceProfileFailureCode,
) -> None:
    error = ImageGenerationRuntimeConfigurationError(
        reason=reason, integration_id="integration", model_identifier="image-model"
    )
    result = _profile_resolution_failure(error)
    assert result.code is code
    assert result.message


def test_image_unusable_code_has_no_catalog_generation_semantics() -> None:
    assert InferenceProfileFailureCode.IMAGE_CATALOG_UNUSABLE.value == (
        "image_catalog_unusable"
    )
