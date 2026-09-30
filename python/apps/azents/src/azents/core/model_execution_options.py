"""Code-owned model execution option definitions and validation."""

import enum
from collections.abc import Collection
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from azents.core.enums import LLMProvider


class ModelExecutionOptionId(enum.StrEnum):
    """Stable identifier for a directly selectable model execution option."""

    FAST = "fast"
    ULTRAFAST = "ultrafast"


class ModelExecutionOptionDefinition(BaseModel):
    """Public metadata for one model execution option."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: ModelExecutionOptionId
    label: str = Field(min_length=1)
    description: str = Field(min_length=1)
    cost_hint: str = Field(min_length=1)
    control: Literal["boolean"]
    exclusive_group: str | None = Field(
        min_length=1,
        description="Registry-owned group allowing at most one enabled option",
    )


_FAST_DEFINITION = ModelExecutionOptionDefinition(
    id=ModelExecutionOptionId.FAST,
    label="Fast",
    description="Request faster processing for supported models.",
    cost_hint="Additional usage or API cost may apply.",
    control="boolean",
    exclusive_group="processing_speed",
)

_ULTRAFAST_DEFINITION = ModelExecutionOptionDefinition(
    id=ModelExecutionOptionId.ULTRAFAST,
    label="Ultrafast",
    description="Request ultrafast processing for supported models.",
    cost_hint=(
        "Additional usage or API cost may apply. "
        "Ultrafast cost estimates are unavailable."
    ),
    control="boolean",
    exclusive_group="processing_speed",
)

MODEL_EXECUTION_OPTION_DEFINITIONS: dict[
    ModelExecutionOptionId, ModelExecutionOptionDefinition
] = {
    ModelExecutionOptionId.FAST: _FAST_DEFINITION,
    ModelExecutionOptionId.ULTRAFAST: _ULTRAFAST_DEFINITION,
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
        selected = validate_supported_execution_options(
            provider=provider,
            supported=supported,
        )
    definitions: list[ModelExecutionOptionDefinition] = []
    for option_id in sorted(selected, key=lambda value: value.value):
        definition = MODEL_EXECUTION_OPTION_DEFINITIONS[option_id]
        hint_suffix = (
            " Ultrafast cost estimates are unavailable."
            if option_id is ModelExecutionOptionId.ULTRAFAST
            else ""
        )
        if provider == LLMProvider.OPENAI:
            definition = definition.model_copy(
                update={
                    "cost_hint": f"Additional OpenAI API cost may apply.{hint_suffix}"
                }
            )
        elif provider == LLMProvider.CHATGPT_OAUTH:
            definition = definition.model_copy(
                update={
                    "cost_hint": (
                        f"Additional ChatGPT usage or credits may apply.{hint_suffix}"
                    )
                }
            )
        definitions.append(definition)
    return definitions


def _canonical_execution_option_ids(
    *,
    options: Collection[ModelExecutionOptionId],
    kind: Literal["Supported", "Enabled"],
) -> list[ModelExecutionOptionId]:
    """Decode implemented IDs, reject duplicates, and return canonical order."""
    try:
        option_ids = [ModelExecutionOptionId(option_id) for option_id in options]
    except (ValueError, TypeError) as error:
        raise ValueError(f"Unknown {kind.lower()} execution option.") from error
    if len(option_ids) != len(set(option_ids)):
        raise ValueError(f"{kind} execution options must be unique.")
    if set(option_ids) - set(MODEL_EXECUTION_OPTION_DEFINITIONS):
        raise ValueError(f"Unknown {kind.lower()} execution option.")
    return sorted(option_ids, key=lambda option_id: option_id.value)


def validate_supported_execution_options(
    *,
    provider: LLMProvider,
    supported: Collection[ModelExecutionOptionId],
) -> list[ModelExecutionOptionId]:
    """Validate model support without treating capabilities as preferences."""
    supported_ids = _canonical_execution_option_ids(
        options=supported,
        kind="Supported",
    )
    if supported_ids and provider not in {
        LLMProvider.OPENAI,
        LLMProvider.CHATGPT_OAUTH,
    }:
        raise ValueError("Execution option is not supported by this provider.")
    return supported_ids


def validate_enabled_execution_options(
    *,
    enabled: Collection[ModelExecutionOptionId],
) -> list[ModelExecutionOptionId]:
    """Validate preference shape and registry-defined group exclusivity."""
    enabled_ids = _canonical_execution_option_ids(options=enabled, kind="Enabled")
    enabled_groups: set[str] = set()
    for option_id in enabled_ids:
        group = MODEL_EXECUTION_OPTION_DEFINITIONS[option_id].exclusive_group
        if group is None:
            continue
        if group in enabled_groups:
            raise ValueError(
                "Enabled execution options must be exclusive within each group."
            )
        enabled_groups.add(group)
    return enabled_ids


def validate_execution_options(
    *,
    provider: LLMProvider,
    supported: Collection[ModelExecutionOptionId],
    enabled: Collection[ModelExecutionOptionId],
) -> list[ModelExecutionOptionId]:
    """Validate enabled preferences against one saved model support snapshot."""
    supported_ids = validate_supported_execution_options(
        provider=provider,
        supported=supported,
    )
    enabled_ids = validate_enabled_execution_options(enabled=enabled)
    if set(enabled_ids) - set(supported_ids):
        raise ValueError("Enabled execution option is not supported by the model.")
    return enabled_ids
