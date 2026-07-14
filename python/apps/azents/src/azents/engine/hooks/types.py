"""runtime hook provider-facing type contracts."""

import dataclasses
from collections.abc import Awaitable, Callable
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, Field

RuntimeHookName = Literal[
    "on_session_start",
    "on_session_clear",
    "on_session_compact",
    "on_compaction_summary",
    "on_session_idle",
    "on_run_start",
    "on_run_end",
    "on_turn_start",
    "on_turn_end",
    "on_before_tool_call",
    "on_after_tool_call",
    "on_runtime_hibernate",
    "on_runtime_restore",
]
ObservationRuntimeHookName = Literal[
    "on_session_start",
    "on_session_clear",
    "on_session_compact",
    "on_session_idle",
    "on_run_start",
    "on_run_end",
    "on_turn_end",
    "on_runtime_hibernate",
    "on_runtime_restore",
]
RunEndReason = Literal["completed", "error", "cancelled", "unknown"]
TurnEndReason = Literal["completed", "error", "cancelled", "unknown"]
TurnPromptPersistence = Literal["visible_user_input", "hidden_internal_input"]
HookTraceStatus = Literal["skipped", "started", "completed", "failed", "cancelled"]


@dataclasses.dataclass(frozen=True)
class SessionStartHookContext:
    """session start hook context."""

    workspace_id: str
    agent_id: str
    session_id: str
    run_id: str | None


@dataclasses.dataclass(frozen=True)
class SessionClearHookContext:
    """session clear hook context."""

    workspace_id: str
    agent_id: str
    session_id: str
    run_id: str | None


@dataclasses.dataclass(frozen=True)
class SessionCompactHookContext:
    """session compact hook context."""

    workspace_id: str
    agent_id: str
    session_id: str
    run_id: str
    owner_generation: int


@dataclasses.dataclass(frozen=True)
class CompactionSummaryHookContext:
    """compaction summary enrichment hook context."""

    workspace_id: str
    agent_id: str
    session_id: str
    run_id: str | None
    compaction_id: str
    reason: str | None
    covered_until_event_id: str
    summary: str
    continuity_history: str


@dataclasses.dataclass(frozen=True)
class SessionIdleHookContext:
    """session idle continuation hook context."""

    workspace_id: str
    agent_id: str
    session_id: str
    run_id: str
    reason: RunEndReason


@dataclasses.dataclass(frozen=True)
class RunStartHookContext:
    """run start hook context."""

    workspace_id: str
    agent_id: str
    session_id: str
    run_id: str
    owner_generation: int


@dataclasses.dataclass(frozen=True)
class RunEndHookContext:
    """run end hook context."""

    workspace_id: str
    agent_id: str
    session_id: str
    run_id: str
    reason: RunEndReason


@dataclasses.dataclass(frozen=True)
class TurnStartHookContext:
    """turn start hook context."""

    workspace_id: str
    agent_id: str
    session_id: str
    run_id: str
    owner_generation: int
    turn_index: int | None


@dataclasses.dataclass(frozen=True)
class TurnEndHookContext:
    """turn end hook context."""

    workspace_id: str
    agent_id: str
    session_id: str
    run_id: str
    reason: TurnEndReason
    turn_index: int | None


@dataclasses.dataclass(frozen=True)
class BeforeToolCallHookContext:
    """pre-tool-execution hook context."""

    tool_name: str
    toolkit_slug: str
    args_json: str
    workspace_id: str
    agent_id: str
    session_id: str
    run_id: str


@dataclasses.dataclass(frozen=True)
class AfterToolCallHookContext:
    """post-tool-execution hook context."""

    tool_name: str
    toolkit_slug: str
    args_json: str
    workspace_id: str
    agent_id: str
    session_id: str
    run_id: str
    owner_generation: int
    output_text: str | None
    error_message: str | None


@dataclasses.dataclass(frozen=True)
class RuntimeHibernateHookContext:
    """runtime hibernate hook context."""

    workspace_id: str | None
    agent_id: str
    session_id: str | None
    agent_runtime_id: str | None


@dataclasses.dataclass(frozen=True)
class RuntimeRestoreHookContext:
    """runtime restore hook context."""

    workspace_id: str | None
    agent_id: str
    session_id: str | None
    agent_runtime_id: str | None


class ToolCallAllow(BaseModel):
    """tool call allow decision."""

    kind: Literal["allow"] = "allow"


class ToolCallDeny(BaseModel):
    """tool call deny decision."""

    kind: Literal["deny"] = "deny"
    message: str


ToolCallDecision = Annotated[ToolCallAllow | ToolCallDeny, Field(discriminator="kind")]


class ToolOutputUnchanged(BaseModel):
    """tool output keep decision."""

    kind: Literal["unchanged"] = "unchanged"


class ToolOutputReplace(BaseModel):
    """tool output replace decision."""

    kind: Literal["replace_output"] = "replace_output"
    output_text: str


ToolOutputDecision = Annotated[
    ToolOutputUnchanged | ToolOutputReplace,
    Field(discriminator="kind"),
]


class CompactionSummaryUnchanged(BaseModel):
    """compaction summary keep decision."""

    kind: Literal["unchanged"] = "unchanged"


class CompactionSummaryReplace(BaseModel):
    """compaction summary replacement decision."""

    kind: Literal["replace_summary"] = "replace_summary"
    summary: str


CompactionSummaryDecision = Annotated[
    CompactionSummaryUnchanged | CompactionSummaryReplace,
    Field(discriminator="kind"),
]


class TurnInjectedPrompt(BaseModel):
    """prompt injected by turn start hook."""

    persistence: TurnPromptPersistence
    text: str
    hook_provider_slug: str | None = None
    hook_prompt_index: int | None = None


class TurnStartResult(BaseModel):
    """Turn start hook result."""

    injected_prompts: list[TurnInjectedPrompt] = Field(default_factory=list)


class SessionContinuationInput(BaseModel):
    """continuation input requested by session idle hook."""

    content: str
    metadata: dict[str, str] = Field(default_factory=dict)
    hook_provider_slug: str | None = None
    hook_continuation_index: int | None = None


class SessionIdleResult(BaseModel):
    """Session idle hook result."""

    continuations: list[SessionContinuationInput] = Field(default_factory=list)


class RuntimeHooks(TypedDict, total=False):
    """explicit hook mapping from lifecycle name to callback."""

    on_session_start: Callable[[SessionStartHookContext], Awaitable[None]]
    on_session_clear: Callable[[SessionClearHookContext], Awaitable[None]]
    on_session_compact: Callable[[SessionCompactHookContext], Awaitable[None]]
    on_compaction_summary: Callable[
        [CompactionSummaryHookContext], Awaitable[CompactionSummaryDecision | None]
    ]
    on_session_idle: Callable[
        [SessionIdleHookContext], Awaitable[SessionIdleResult | None]
    ]
    on_run_start: Callable[[RunStartHookContext], Awaitable[None]]
    on_run_end: Callable[[RunEndHookContext], Awaitable[None]]
    on_turn_start: Callable[[TurnStartHookContext], Awaitable[TurnStartResult | None]]
    on_turn_end: Callable[[TurnEndHookContext], Awaitable[None]]
    on_before_tool_call: Callable[
        [BeforeToolCallHookContext], Awaitable[ToolCallDecision | None]
    ]
    on_after_tool_call: Callable[
        [AfterToolCallHookContext], Awaitable[ToolOutputDecision | None]
    ]
    on_runtime_hibernate: Callable[[RuntimeHibernateHookContext], Awaitable[None]]
    on_runtime_restore: Callable[[RuntimeRestoreHookContext], Awaitable[None]]


def normalize_turn_start_result(result: TurnStartResult | None) -> TurnStartResult:
    """Normalize turn start hook result with default."""
    if result is None:
        return TurnStartResult()
    return result


def normalize_before_tool_call_result(
    result: ToolCallDecision | None,
) -> ToolCallDecision:
    """Normalize before tool hook result with allow default."""
    if result is None:
        return ToolCallAllow()
    return result


def normalize_after_tool_call_result(
    result: ToolOutputDecision | None,
) -> ToolOutputDecision:
    """Normalize after tool hook result with unchanged default."""
    if result is None:
        return ToolOutputUnchanged()
    return result


def normalize_compaction_summary_result(
    result: CompactionSummaryDecision | None,
) -> CompactionSummaryDecision:
    """Normalize compaction summary hook result with unchanged default."""
    if result is None:
        return CompactionSummaryUnchanged()
    return result


def normalize_session_idle_result(
    result: SessionIdleResult | None,
) -> SessionIdleResult:
    """Normalize session idle hook result with default."""
    if result is None:
        return SessionIdleResult()
    return result
