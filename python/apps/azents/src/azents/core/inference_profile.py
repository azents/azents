"""Requested and user-safe inference profile contracts."""

import enum

from pydantic import BaseModel, ConfigDict, Field

from azents.core.agent import AgentModelSelection
from azents.core.enums import AgentRunStatus, LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import ModelReasoningEffort


class InferenceProfileSource(enum.StrEnum):
    """Source of requested inference intent for an AgentRun."""

    EXPLICIT_INPUT = "explicit_input"
    SESSION_LAST_USED = "session_last_used"
    AGENT_DEFAULT = "agent_default"
    PARENT_RUN = "parent_run"
    RETRY_ORIGINAL = "retry_original"


class InferenceProfileFailureCode(enum.StrEnum):
    """User-safe inference profile resolution failure code."""

    MODEL_TARGET_NOT_FOUND = "model_target_not_found"
    MODEL_TARGET_RESOLUTION_FAILED = "model_target_resolution_failed"
    REASONING_EFFORT_UNSUPPORTED = "reasoning_effort_unsupported"


class RequestedInferenceProfile(BaseModel):
    """Agent-owned target label and optional explicit reasoning effort."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_target_label: str = Field(
        min_length=1,
        description="Agent-owned selectable model target label",
    )
    reasoning_effort: ModelReasoningEffort | None = Field(
        description="Explicit reasoning effort, or null for model Default",
    )


class ResolvedInferenceProfileSummary(BaseModel):
    """Allowlisted resolved model identity safe for public projection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: LLMProvider = Field(description="Resolved hosting provider")
    model_identifier: str = Field(description="Resolved provider model identifier")
    model_display_name: str = Field(description="Resolved model display name")
    model_developer: LLMModelDeveloper = Field(description="Resolved model developer")

    @classmethod
    def from_model_selection(
        cls,
        selection: AgentModelSelection,
    ) -> "ResolvedInferenceProfileSummary":
        """Build a safe summary without integration or catalog snapshot data."""
        return cls(
            provider=selection.provider,
            model_identifier=selection.model_identifier,
            model_display_name=selection.model_display_name,
            model_developer=selection.model_developer,
        )


class InferenceRunSummary(BaseModel):
    """Compact allowlisted inference provenance for a user message."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(description="Associated AgentRun ID")
    run_index: int = Field(ge=1, description="Session-local AgentRun index")
    status: AgentRunStatus = Field(description="Latest associated run status")
    requested_profile: RequestedInferenceProfile | None = Field(
        description="Requested inference intent when available",
    )
    source: InferenceProfileSource | None = Field(
        description="Requested inference profile source when available",
    )
    resolved_profile: ResolvedInferenceProfileSummary | None = Field(
        description="Safe resolved model summary when resolution succeeded",
    )
    resolved_reasoning_effort: ModelReasoningEffort | None = Field(
        description="Effective explicit effort, or null for model Default",
    )
    effective_context_window_tokens: int | None = Field(
        ge=1,
        description="Context window limit fixed for the run",
    )
    effective_auto_compaction_threshold_tokens: int | None = Field(
        ge=1,
        description="Auto-compaction threshold fixed for the run",
    )
    failure_code: InferenceProfileFailureCode | None = Field(
        description="Safe profile resolution failure code",
    )
    failure_message: str | None = Field(
        description="User-safe profile resolution failure message",
    )
