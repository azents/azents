"""Ephemeral event types yielded by Engine."""

import datetime
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

from azents.core.enums import AgentRunPhase


class ContentDelta(BaseModel):
    """Text chunk streaming event."""

    model_config = ConfigDict(frozen=True)

    type: Literal["content_delta"] = "content_delta"
    delta: str
    content_index: int


class FunctionCallDelta(BaseModel):
    """Function tool call argument chunk streaming event."""

    model_config = ConfigDict(frozen=True)

    type: Literal["function_call_delta"] = "function_call_delta"
    index: int
    id: str | None
    name: str | None
    arguments_delta: str


class ReasoningDelta(BaseModel):
    """Reasoning summary Text chunk streaming event."""

    model_config = ConfigDict(frozen=True)

    type: Literal["reasoning_delta"] = "reasoning_delta"
    delta: str


class ProviderToolActivityChanged(BaseModel):
    """Provider-neutral hosted-tool activity snapshot."""

    model_config = ConfigDict(frozen=True)

    type: Literal["provider_tool_activity_changed"] = "provider_tool_activity_changed"
    call_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    status: Literal["running", "completed", "failed"]
    arguments: str | None


class RunStarted(BaseModel):
    """Run started event."""

    model_config = ConfigDict(frozen=True)

    type: Literal["run_started"] = "run_started"
    run_id: str
    phase: AgentRunPhase | None = None


class RunPhaseChanged(BaseModel):
    """Run phase changed event."""

    model_config = ConfigDict(frozen=True)

    type: Literal["run_phase_changed"] = "run_phase_changed"
    run_id: str
    phase: AgentRunPhase
    model_call_started_at: datetime.datetime | None


class RunComplete(BaseModel):
    """Run complete event."""

    model_config = ConfigDict(frozen=True)

    type: Literal["run_complete"] = "run_complete"
    run_id: str


class RunStopped(BaseModel):
    """User stopped event."""

    model_config = ConfigDict(frozen=True)

    type: Literal["run_stopped"] = "run_stopped"
    run_id: str


class RuntimeInitializingEvent(BaseModel):
    """Runtime allocation started event."""

    model_config = ConfigDict(frozen=True)

    type: Literal["runtime_initializing"] = "runtime_initializing"


class RuntimeReadyEvent(BaseModel):
    """Runtime ready event."""

    model_config = ConfigDict(frozen=True)

    type: Literal["runtime_ready"] = "runtime_ready"


class RuntimeProcessOutputDeltaEvent(BaseModel):
    """Runtime process stdout/stderr live output delta."""

    model_config = ConfigDict(frozen=True)

    type: Literal["runtime_process_output_delta"] = "runtime_process_output_delta"
    process_id: str
    stream: Literal["stdout", "stderr"]
    chunk_id: int
    text: str
    truncated: bool = False
    omitted_bytes: int = 0


class RuntimeErrorEvent(BaseModel):
    """Runtime error event."""

    model_config = ConfigDict(frozen=True)

    type: Literal["runtime_error"] = "runtime_error"
    message: str


class AuthorizationRequestEvent(BaseModel):
    """OAuth authorization request event."""

    model_config = ConfigDict(frozen=True)

    type: Literal["authorization_request"] = "authorization_request"
    toolkit_id: str
    toolkit_name: str


class AccountLinkNudgeEvent(BaseModel):
    """Account connection guide event."""

    model_config = ConfigDict(frozen=True)

    type: Literal["account_link_nudge"] = "account_link_nudge"
    toolkit_name: str
    toolkit_type: str
    toolkit_id: str


class CompactionStarted(BaseModel):
    """Compaction started event."""

    model_config = ConfigDict(frozen=True)

    type: Literal["compaction_started"] = "compaction_started"
    continuing: bool = False


class CompactionComplete(BaseModel):
    """Compaction complete event."""

    model_config = ConfigDict(frozen=True)

    type: Literal["compaction_complete"] = "compaction_complete"
    continuing: bool = False


class TodoStateChanged(BaseModel):
    """Session todo state changed event."""

    model_config = ConfigDict(frozen=True)

    type: Literal["todo_state_changed"] = "todo_state_changed"
    todo: dict[str, object]


class SubagentTreeChanged(BaseModel):
    """Subagent Tree invalidation event."""

    model_config = ConfigDict(frozen=True)

    type: Literal["subagent_tree_changed"] = "subagent_tree_changed"
    root_session_agent_id: str
    changed_session_agent_id: str


EngineEvent: TypeAlias = Annotated[
    ContentDelta
    | ReasoningDelta
    | FunctionCallDelta
    | ProviderToolActivityChanged
    | RunStarted
    | RunPhaseChanged
    | RunComplete
    | RunStopped
    | RuntimeInitializingEvent
    | RuntimeReadyEvent
    | RuntimeProcessOutputDeltaEvent
    | RuntimeErrorEvent
    | AuthorizationRequestEvent
    | AccountLinkNudgeEvent
    | CompactionStarted
    | TodoStateChanged
    | SubagentTreeChanged
    | CompactionComplete,
    Field(discriminator="type"),
]
