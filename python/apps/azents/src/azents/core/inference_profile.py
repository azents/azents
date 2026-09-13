"""Requested and user-safe inference profile contracts."""

import datetime
import enum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    WithJsonSchema,
    field_validator,
    model_validator,
)

from azents.core.agent import (
    AgentModelSelection,
    SelectableModelOption,
    SelectableModelSettings,
)
from azents.core.enums import LLMProvider
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.model_execution_options import (
    ModelExecutionOptionId,
    validate_execution_options,
)

PublicReasoningEffort = Annotated[
    ModelReasoningEffort | None,
    WithJsonSchema({"anyOf": [{"type": "string"}, {"type": "null"}]}),
]


def _canonical_enabled_execution_options(
    enabled: list[ModelExecutionOptionId],
) -> list[ModelExecutionOptionId]:
    """Validate unique option IDs and return canonical ordering."""
    if len(enabled) != len(set(enabled)):
        raise ValueError("Enabled execution options must be unique.")
    return sorted(enabled, key=lambda option: option.value)


def default_historical_execution_options(data: object) -> object:
    """Decode historical profile payloads that predate execution options."""
    if not isinstance(data, dict) or "enabled_execution_options" in data:
        return data
    return {**data, "enabled_execution_options": []}


def normalize_historical_inference_profile_payload(
    payload: dict[str, object],
) -> dict[str, object]:
    """Normalize a nested historical inference profile for equality checks."""
    profile = payload.get("inference_profile")
    normalized_profile = default_historical_execution_options(profile)
    if normalized_profile is profile:
        return payload
    return {**payload, "inference_profile": normalized_profile}


class InferenceProfileSource(enum.StrEnum):
    """Source of requested inference intent for an AgentRun."""

    EXPLICIT_INPUT = "explicit_input"
    SESSION_LAST_USED = "session_last_used"
    AGENT_DEFAULT = "agent_default"
    PARENT_RUN = "parent_run"
    SPAWN_OVERRIDE = "spawn_override"
    RETRY_ORIGINAL = "retry_original"


class InferenceProfileFailureCode(enum.StrEnum):
    """User-safe inference profile resolution failure code."""

    MODEL_TARGET_NOT_FOUND = "model_target_not_found"
    MODEL_TARGET_RESOLUTION_FAILED = "model_target_resolution_failed"
    MODEL_CANDIDATE_CHAIN_EXHAUSTED = "model_candidate_chain_exhausted"
    REASONING_EFFORT_UNSUPPORTED = "reasoning_effort_unsupported"
    EXECUTION_OPTION_UNSUPPORTED = "execution_option_unsupported"
    IMAGE_INTEGRATION_DISABLED = "integration_disabled"
    IMAGE_EXPLICIT_SELECTION_UNSUPPORTED = "explicit_selection_unsupported"
    IMAGE_CATALOG_UNAVAILABLE = "catalog_unavailable"
    IMAGE_CATALOG_GENERATION_MISMATCH = "catalog_generation_mismatch"
    IMAGE_MODEL_UNAVAILABLE = "model_unavailable"
    IMAGE_PROVIDER_MODEL_MISMATCH = "provider_model_mismatch"


class RequestedInferenceProfile(BaseModel):
    """Agent-owned target label and optional explicit reasoning effort."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_target_label: str = Field(
        min_length=1,
        description="Agent-owned selectable model target label",
    )
    reasoning_effort: PublicReasoningEffort = Field(
        description="Explicit reasoning effort, or null for model Default",
    )
    enabled_execution_options: list[ModelExecutionOptionId] = Field(
        description="Explicitly enabled model execution option IDs",
    )

    _decode_historical_execution_options = model_validator(mode="before")(
        default_historical_execution_options
    )
    _validate_enabled_execution_options = field_validator("enabled_execution_options")(
        _canonical_enabled_execution_options
    )


class AppliedInferenceProfile(BaseModel):
    """Resolved user-visible inference settings applied by one message."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_target_label: str = Field(
        min_length=1,
        description="Agent-owned model target label applied by the message",
    )
    model_display_name: str | None = Field(
        default=None,
        min_length=1,
        description="Resolved model display name, or null before preparation",
    )
    reasoning_effort: PublicReasoningEffort = Field(
        description="Applied explicit effort, or null for model Default",
    )
    enabled_execution_options: list[ModelExecutionOptionId] = Field(
        description="Model execution option IDs applied by the message",
    )

    _decode_historical_execution_options = model_validator(mode="before")(
        default_historical_execution_options
    )
    _validate_enabled_execution_options = field_validator("enabled_execution_options")(
        _canonical_enabled_execution_options
    )


class SessionAppliedInferenceProfile(BaseModel):
    """Agent-owned model intent applied to a Session."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_target_label: str = Field(
        min_length=1,
        description="Agent-owned model target label applied to the Session",
    )
    reasoning_effort: PublicReasoningEffort = Field(
        description="Applied explicit effort, or null for model Default",
    )
    enabled_execution_options: list[ModelExecutionOptionId] = Field(
        description="Model execution option IDs applied to the Session",
    )

    _validate_enabled_execution_options = field_validator("enabled_execution_options")(
        _canonical_enabled_execution_options
    )


class AppliedModelRoute(BaseModel):
    """Immutable physical model route used by one logical model operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: str = Field(min_length=1)
    operation_kind: Literal["foreground", "compaction", "title"]
    candidate_ordinal: int = Field(ge=1, le=5)
    candidate_role: Literal["primary", "fallback"]
    provider: LLMProvider
    llm_provider_integration_id: str = Field(min_length=1)
    model_identifier: str = Field(min_length=1)
    model_display_name: str = Field(min_length=1)
    effective_context_window_tokens: int = Field(gt=0)
    effective_auto_compaction_threshold_tokens: int = Field(gt=0)


def validate_requested_profile_against_options(
    options: list[SelectableModelOption],
    profile: RequestedInferenceProfile,
) -> SelectableModelOption:
    """Validate one Agent-owned profile against a locked option snapshot."""
    option = next(
        (
            candidate
            for candidate in options
            if candidate.label == profile.model_target_label
        ),
        None,
    )
    if option is None:
        raise ValueError("Model target label is not available")
    if (
        profile.reasoning_effort is not None
        and profile.reasoning_effort
        not in option.candidates[
            0
        ].model_selection.normalized_capabilities.reasoning.effort_levels
    ):
        raise ValueError("Reasoning effort is not supported by model target")
    validate_execution_options(
        provider=option.candidates[0].model_selection.provider,
        supported=option.candidates[0].model_selection.supported_execution_options,
        enabled=profile.enabled_execution_options,
    )
    return option


class SessionInferenceState(BaseModel):
    """Complete resolved inference configuration prepared for the next turn."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_target_label: str = Field(min_length=1)
    model_selection: AgentModelSelection
    model_settings: SelectableModelSettings
    reasoning_effort: ModelReasoningEffort | None
    enabled_execution_options: list[ModelExecutionOptionId]
    effective_context_window_tokens: int = Field(gt=0)
    effective_auto_compaction_threshold_tokens: int = Field(gt=0)
    resolved_at: datetime.datetime
    applied_model_route: AppliedModelRoute | None = Field(
        default=None,
        description="Physical candidate route applied to the current model call",
    )

    _validate_enabled_execution_options = field_validator("enabled_execution_options")(
        _canonical_enabled_execution_options
    )

    @property
    def applied_profile(self) -> AppliedInferenceProfile:
        """Return the user-visible settings represented by this state."""
        return AppliedInferenceProfile(
            model_target_label=self.model_target_label,
            model_display_name=self.model_selection.model_display_name,
            reasoning_effort=self.reasoning_effort,
            enabled_execution_options=self.enabled_execution_options,
        )
