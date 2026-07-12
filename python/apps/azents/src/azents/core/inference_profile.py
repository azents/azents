"""Requested and user-safe inference profile contracts."""

import datetime
import enum

from pydantic import BaseModel, ConfigDict, Field

from azents.core.agent import AgentModelSelection
from azents.core.llm_catalog import ModelReasoningEffort


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


class AppliedInferenceProfile(BaseModel):
    """Resolved user-visible inference settings applied by one message."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_target_label: str = Field(
        min_length=1,
        description="Agent-owned model target label applied by the message",
    )
    reasoning_effort: ModelReasoningEffort | None = Field(
        description="Applied explicit effort, or null for model Default",
    )


class SessionInferenceState(BaseModel):
    """Complete resolved inference configuration prepared for the next turn."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_target_label: str = Field(min_length=1)
    model_selection: AgentModelSelection
    reasoning_effort: ModelReasoningEffort | None
    effective_context_window_tokens: int = Field(gt=0)
    effective_auto_compaction_threshold_tokens: int = Field(gt=0)
    resolved_at: datetime.datetime

    @property
    def applied_profile(self) -> AppliedInferenceProfile:
        """Return the user-visible settings represented by this state."""
        return AppliedInferenceProfile(
            model_target_label=self.model_target_label,
            reasoning_effort=self.reasoning_effort,
        )
