"""Agent Runtime removal scope repository data models."""

import dataclasses


@dataclasses.dataclass(frozen=True)
class AgentRuntimeRemovalImpact:
    """Privacy-safe aggregate impact of one Runtime removal."""

    active_root_session_count: int
    active_subagent_count: int
    active_run_count: int
    queued_runtime_action_count: int


@dataclasses.dataclass(frozen=True)
class AgentRuntimeRemovalInterruption:
    """Durable interruption result for one Agent."""

    stop_session_ids: tuple[str, ...]
    cancelled_runtime_action_count: int
    active_work_remaining: bool


@dataclasses.dataclass(frozen=True)
class AgentRuntimeRemovalCleanupBatch:
    """One bounded product-state cleanup batch."""

    cursor_context_id: str | None
    scanned_count: int
    invalidated_count: int
    completed: bool
