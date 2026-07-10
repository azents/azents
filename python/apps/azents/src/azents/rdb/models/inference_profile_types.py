"""Inference profile PostgreSQL enum mappings."""

import enum

from sqlalchemy.dialects.postgresql import ENUM

from azents.core.inference_profile import (
    InferenceProfileFailureCode,
    InferenceProfileSource,
)
from azents.core.llm_catalog import ModelReasoningEffort


def _enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """Return StrEnum values stored in the DB."""
    return [value.value for value in enum_cls]


model_reasoning_effort_enum = ENUM(
    ModelReasoningEffort,
    name="model_reasoning_effort",
    create_type=False,
    values_callable=_enum_values,
)
inference_profile_source_enum = ENUM(
    InferenceProfileSource,
    name="inference_profile_source",
    create_type=False,
    values_callable=_enum_values,
)
inference_profile_failure_code_enum = ENUM(
    InferenceProfileFailureCode,
    name="inference_profile_failure_code",
    create_type=False,
    values_callable=_enum_values,
)
