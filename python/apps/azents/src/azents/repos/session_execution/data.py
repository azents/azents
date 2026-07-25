"""Canonical durable Session execution projection data."""

import dataclasses
import datetime

from azents.core.enums import AgentRunStatus, AgentSessionKind


@dataclasses.dataclass(frozen=True)
class PendingCommandSnapshot:
    """One complete durable command selected for Session execution."""

    id: str
    name: str
    payload: dict[str, object]
    requester_user_id: str | None
    created_at: datetime.datetime


@dataclasses.dataclass(frozen=True)
class CanonicalExecutionSnapshot:
    """Immutable validated execution identity and work expectation."""

    session_id: str
    root_session_id: str
    workspace_id: str
    workspace_handle: str
    agent_id: str
    session_agent_id: str
    root_session_agent_id: str
    session_agent_context_id: str
    execution_mode: AgentSessionKind
    owner_generation: int
    fifo_input_buffer_id: str | None
    pending_command: PendingCommandSnapshot | None
    recoverable_run_id: str | None
    recoverable_run_status: AgentRunStatus | None
    pending_idle_continuation_run_id: str | None
