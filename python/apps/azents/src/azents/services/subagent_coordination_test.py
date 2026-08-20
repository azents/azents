"""Subagent coordination projection service tests."""

import datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRunStatus,
    AgentSessionRunState,
    SessionAgentKind,
)
from azents.repos.subagent_coordination.data import (
    SubagentCoordinationSnapshot,
    SubagentCoordinationSnapshotRow,
)
from azents.repos.subagent_coordination.repository import (
    SubagentCoordinationRepository,
)

from .subagent_coordination import SubagentCoordinationService

_NOW = datetime.datetime.now(datetime.UTC)


def _row(
    *,
    path: str,
    session_run_state: AgentSessionRunState,
    latest_run_status: AgentRunStatus | None,
    kind: SessionAgentKind,
) -> SubagentCoordinationSnapshotRow:
    """Build one repository projection row."""
    slug = path.rsplit("/", 1)[-1]
    return SubagentCoordinationSnapshotRow(
        session_agent_id=f"{slug}-agent",
        agent_session_id=f"{slug}-session",
        kind=kind,
        path=path,
        last_message_at=_NOW,
        created_at=_NOW,
        session_run_state=session_run_state,
        latest_run_status=latest_run_status,
        wake_pending=False,
        required=session_run_state == AgentSessionRunState.RUNNING
        or latest_run_status in {AgentRunStatus.PENDING, AgentRunStatus.RUNNING},
    )


class _Repository(SubagentCoordinationRepository):
    """SubagentCoordinationRepository fake."""

    def __init__(self, snapshot: SubagentCoordinationSnapshot | None) -> None:
        """Initialize the configured snapshot."""
        self.snapshot = snapshot
        self.calls: list[tuple[str, int]] = []

    async def project_root_tree(
        self,
        session: AsyncSession,
        *,
        current_session_id: str,
        configured_capacity: int,
    ) -> SubagentCoordinationSnapshot | None:
        """Return the configured snapshot."""
        del session
        self.calls.append((current_session_id, configured_capacity))
        return self.snapshot


def _session() -> AsyncSession:
    """Build one unused typed session double."""
    return AsyncMock(spec=AsyncSession)


@pytest.mark.parametrize(
    ("session_run_state", "latest_run_status", "expected_status"),
    [
        (AgentSessionRunState.RUNNING, None, "running"),
        (AgentSessionRunState.IDLE, None, "idle"),
        (AgentSessionRunState.IDLE, AgentRunStatus.PENDING, "pending"),
        (AgentSessionRunState.IDLE, AgentRunStatus.RUNNING, "running"),
        (AgentSessionRunState.IDLE, AgentRunStatus.COMPLETED, "completed"),
        (AgentSessionRunState.IDLE, AgentRunStatus.FAILED, "errored"),
        (AgentSessionRunState.IDLE, AgentRunStatus.STOPPED, "interrupted"),
        (AgentSessionRunState.IDLE, AgentRunStatus.INTERRUPTED, "interrupted"),
        (AgentSessionRunState.IDLE, AgentRunStatus.CANCELLED, "interrupted"),
    ],
)
async def test_list_agents_projects_bounded_statuses(
    session_run_state: AgentSessionRunState,
    latest_run_status: AgentRunStatus | None,
    expected_status: str,
) -> None:
    """Map durable session and latest-Run state to the canonical status string."""
    snapshot = SubagentCoordinationSnapshot(
        rows=(
            _row(
                path="/root/child",
                session_run_state=session_run_state,
                latest_run_status=latest_run_status,
                kind=SessionAgentKind.SUBAGENT,
            ),
        ),
        configured_capacity=2,
        required_count=1,
        selected_inactive_count=0,
        omitted_inactive_count=3,
    )
    repository = _Repository(snapshot)
    service = SubagentCoordinationService(repository=repository)

    projection = await service.list_agents(
        _session(),
        current_session_id="child-session",
        configured_capacity=2,
    )

    assert projection is not None
    assert projection.agents[0].agent_name == "/root/child"
    assert projection.agents[0].agent_status == expected_status
    assert projection.configured_capacity == 2
    assert projection.required_count == 1
    assert projection.selected_inactive_count == 0
    assert projection.omitted_inactive_count == 3
    assert repository.calls == [("child-session", 2)]


async def test_list_agents_preserves_root_first_canonical_rows() -> None:
    """Preserve repository selection order and canonical paths without extra fields."""
    snapshot = SubagentCoordinationSnapshot(
        rows=(
            _row(
                path="/root",
                session_run_state=AgentSessionRunState.RUNNING,
                latest_run_status=None,
                kind=SessionAgentKind.ROOT,
            ),
            _row(
                path="/root/a",
                session_run_state=AgentSessionRunState.IDLE,
                latest_run_status=AgentRunStatus.COMPLETED,
                kind=SessionAgentKind.SUBAGENT,
            ),
        ),
        configured_capacity=1,
        required_count=0,
        selected_inactive_count=1,
        omitted_inactive_count=4,
    )
    service = SubagentCoordinationService(repository=_Repository(snapshot))

    projection = await service.list_agents(
        _session(),
        current_session_id="root-session",
        configured_capacity=1,
    )

    assert projection is not None
    assert [(agent.agent_name, agent.agent_status) for agent in projection.agents] == [
        ("/root", "running"),
        ("/root/a", "completed"),
    ]


async def test_list_agents_returns_none_for_missing_current_tree() -> None:
    """Propagate missing current/root identity to the Toolkit error boundary."""
    service = SubagentCoordinationService(repository=_Repository(None))

    projection = await service.list_agents(
        _session(),
        current_session_id="missing-session",
        configured_capacity=3,
    )

    assert projection is None
