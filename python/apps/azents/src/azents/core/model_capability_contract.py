"""Deterministic request constraints for the single final capability view."""

import enum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

type ReasoningEffortValue = Literal[
    "none", "minimal", "low", "medium", "high", "xhigh", "max"
]
type ModalityValue = Literal["text", "image", "pdf", "audio", "video"]
type BuiltinToolValue = Literal["web_search", "image_generation"]


class ModelCapabilityFeature(enum.StrEnum):
    """Stable keys for features derived from the final boolean/list fields."""

    FUNCTION_CALLING = "function_calling"
    PARALLEL_FUNCTION_CALLS = "parallel_function_calls"
    STRICT_FUNCTION_SCHEMA = "strict_function_schema"
    STRUCTURED_RESPONSE = "structured_response"
    REASONING = "reasoning"
    REASONING_SUMMARIES = "reasoning_summaries"
    TEMPERATURE = "temperature"
    MAX_OUTPUT_TOKENS = "max_output_tokens"
    TOP_P = "top_p"
    TOP_K = "top_k"
    STOP_SEQUENCES = "stop_sequences"
    INPUT_TEXT = "input:text"
    INPUT_IMAGE = "input:image"
    INPUT_PDF = "input:pdf"
    INPUT_AUDIO = "input:audio"
    INPUT_VIDEO = "input:video"
    OUTPUT_TEXT = "output:text"
    OUTPUT_IMAGE = "output:image"
    OUTPUT_PDF = "output:pdf"
    OUTPUT_AUDIO = "output:audio"
    OUTPUT_VIDEO = "output:video"
    WEB_SEARCH = "builtin:web_search"
    IMAGE_GENERATION = "builtin:image_generation"


class ModelFeatureCondition(BaseModel):
    """Constrain a present feature without defining a second support fact.

    Null means that a request dimension is unconstrained. Consumers evaluate
    these conditions against the complete effective request, never raw settings.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    feature: ModelCapabilityFeature
    reasoning_efforts: tuple[ReasoningEffortValue, ...] | None
    function_tools: bool | None

    @model_validator(mode="after")
    def validate_condition(self) -> Self:
        """Reject empty constraints and duplicate or empty effort domains."""
        if self.reasoning_efforts is None and self.function_tools is None:
            raise ValueError("A feature condition requires a request constraint.")
        if self.reasoning_efforts is not None:
            if not self.reasoning_efforts:
                raise ValueError("A feature condition requires accepted efforts.")
            if len(self.reasoning_efforts) != len(set(self.reasoning_efforts)):
                raise ValueError("Feature condition efforts must be unique.")
        return self


class ModelRequestConstraints(BaseModel):
    """Known request metadata, independent of final feature membership.

    A missing default is omitted knowledge, not another feature support state.
    The final capability fields alone determine whether a feature is present.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    known_default: ReasoningEffortValue | None = None
    feature_conditions: tuple[ModelFeatureCondition, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_unique_conditions(self) -> Self:
        """Keep one deterministic conjunction per feature."""
        features = [condition.feature for condition in self.feature_conditions]
        if len(features) != len(set(features)):
            raise ValueError("Feature conditions must be unique.")
        return self
