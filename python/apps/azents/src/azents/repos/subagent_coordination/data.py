"""Subagent coordination repository data."""

import dataclasses
import datetime

from azents.core.enums import (
    AgentRunStatus,
    AgentSessionRunState,
    SessionAgentKind,
)


@dataclasses.dataclass(frozen=True)
class SubagentCoordinationSnapshotRow:
    """One selected root-tree coordination row."""

    session_agent_id: str
    agent_session_id: str
    kind: SessionAgentKind
    path: str
    last_message_at: datetime.datetime | None
    created_at: datetime.datetime
    session_run_state: AgentSessionRunState
    latest_run_status: AgentRunStatus | None
    wake_pending: bool
    required: bool


@dataclasses.dataclass(frozen=True)
class SubagentCoordinationSnapshot:
    """Bounded root-tree coordination snapshot."""

    rows: tuple[SubagentCoordinationSnapshotRow, ...]
    configured_capacity: int
    required_count: int
    selected_inactive_count: int
    omitted_inactive_count: int
