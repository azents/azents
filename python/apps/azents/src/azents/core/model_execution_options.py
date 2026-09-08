"""Code-owned model execution option definitions and validation."""

import enum
from collections.abc import Collection
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from azents.core.enums import LLMProvider


class ModelExecutionOptionId(enum.StrEnum):
    """Stable identifier for a directly selectable model execution option."""

    FAST = "fast"


class ModelExecutionOptionDefinition(BaseModel):
    """Public metadata for one model execution option."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: ModelExecutionOptionId
    label: str = Field(min_length=1)
    description: str = Field(min_length=1)
    cost_hint: str = Field(min_length=1)
    control: Literal["boolean"]


_FAST_DEFINITION = ModelExecutionOptionDefinition(
    id=ModelExecutionOptionId.FAST,
    label="Fast",
    description="Request faster processing for supported models.",
    cost_hint="Additional usage or API cost may apply.",
    control="boolean",
)

MODEL_EXECUTION_OPTION_DEFINITIONS: dict[
    ModelExecutionOptionId, ModelExecutionOptionDefinition
] = {
    ModelExecutionOptionId.FAST: _FAST_DEFINITION,
}


def list_model_execution_option_definitions(
    *,
    provider: LLMProvider | None = None,
    supported: Collection[ModelExecutionOptionId] | None = None,
) -> list[ModelExecutionOptionDefinition]:
    """Return definitions, or filter them for one concrete provider/model.

    ``provider`` may be omitted only when listing every known definition. A
    provider is required when ``supported`` is supplied so provider-specific
    public hints and support validation remain authoritative.
    """
    if supported is None:
        selected = MODEL_EXECUTION_OPTION_DEFINITIONS.keys()
    else:
        if provider is None:
            raise ValueError("Provider is required when filtering definitions.")
        selected = validate_execution_options(
            provider=provider,
            supported=supported,
            enabled=supported,
        )
    definitions: list[ModelExecutionOptionDefinition] = []
    for option_id in sorted(selected, key=lambda value: value.value):
        definition = MODEL_EXECUTION_OPTION_DEFINITIONS[option_id]
        if provider == LLMProvider.OPENAI and option_id is ModelExecutionOptionId.FAST:
            definition = definition.model_copy(
                update={"cost_hint": "Additional OpenAI API cost may apply."}
            )
        elif (
            provider == LLMProvider.CHATGPT_OAUTH
            and option_id is ModelExecutionOptionId.FAST
        ):
            definition = definition.model_copy(
                update={"cost_hint": "Additional ChatGPT usage or credits may apply."}
            )
        definitions.append(definition)
    return definitions


def validate_execution_options(
    *,
    provider: LLMProvider,
    supported: Collection[ModelExecutionOptionId],
    enabled: Collection[ModelExecutionOptionId],
) -> list[ModelExecutionOptionId]:
    """Validate and canonically order supported and enabled option IDs."""
    supported_ids = list(supported)
    enabled_ids = list(enabled)
    if provider not in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH} and (
        ModelExecutionOptionId.FAST in supported_ids
        or ModelExecutionOptionId.FAST in enabled_ids
    ):
        raise ValueError("Fast execution is not supported by this provider.")
    if len(supported_ids) != len(set(supported_ids)):
        raise ValueError("Supported execution options must be unique.")
    if len(enabled_ids) != len(set(enabled_ids)):
        raise ValueError("Enabled execution options must be unique.")
    unknown_supported = set(supported_ids) - set(MODEL_EXECUTION_OPTION_DEFINITIONS)
    if unknown_supported:
        raise ValueError("Unknown supported execution option.")
    unknown_enabled = set(enabled_ids) - set(MODEL_EXECUTION_OPTION_DEFINITIONS)
    if unknown_enabled:
        raise ValueError("Unknown enabled execution option.")
    unsupported = set(enabled_ids) - set(supported_ids)
    if unsupported:
        raise ValueError("Enabled execution option is not supported by the model.")
    return sorted(enabled_ids, key=lambda value: value.value)
