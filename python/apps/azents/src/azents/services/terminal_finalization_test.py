"""Terminal Run finalization tests."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRunParentResultDeliveryState,
    AgentRunPhase,
    AgentRunStatus,
    AgentSessionStatus,
    SessionAgentKind,
)
from azents.engine.events.types import AgentRunState
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import SessionAgent
from azents.services.agent_mailbox import AgentMailboxService
from azents.services.terminal_finalization import (
    TerminalDeliveryDisposition,
    TerminalRunFinalizationCoordinator,
)


class _AgentRunRepository:
    """AgentRunRepository test double."""

    def __init__(self, run: AgentRunState) -> None:
        self.run = run

    async def get_by_id(
        self,
        session: AsyncSession,
        run_id: str,
    ) -> AgentRunState | None:
        """Return the configured Run."""
        del session
        return self.run if self.run.id == run_id else None

    async def lock_by_id(
        self,
        session: AsyncSession,
        run_id: str,
    ) -> AgentRunState | None:
        """Return the configured Run under the simulated lock."""
        return await self.get_by_id(session, run_id)

    async def mark_stopped_for_user_stop(
        self,
        session: AsyncSession,
        run_id: str,
        *,
        ended_at: datetime,
    ) -> AgentRunState | None:
        """Converge the configured Run to User Stop."""
        del session
        if self.run.id != run_id:
            return None
        self.run = self.run.model_copy(
            update={
                "status": AgentRunStatus.STOPPED,
                "ended_at": ended_at,
                "terminal_result_event_id": None,
                "terminal_result_message": None,
            }
        )
        return self.run

    async def mark_parent_result_enqueued(
        self,
        session: AsyncSession,
        *,
        run_id: str,
        mailbox_item_id: str,
        enqueued_at: datetime,
    ) -> AgentRunState:
        """Record the simulated parent delivery."""
        del session
        if self.run.id != run_id:
            raise ValueError("AgentRun not found")
        self.run = self.run.model_copy(
            update={
                "parent_result_delivery_state": (
                    AgentRunParentResultDeliveryState.ENQUEUED
                ),
                "parent_result_mailbox_item_id": mailbox_item_id,
                "parent_result_enqueued_at": enqueued_at,
            }
        )
        return self.run


class _AgentSessionRepository:
    """AgentSessionRepository test double."""

    def __init__(self, source: SessionAgent, parent: SessionAgent) -> None:
        self.source = source
        self.parent = parent

    async def has_stop_request(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> bool:
        """Return a durable User Stop for the source Session."""
        del session
        return session_id == self.source.agent_session_id

    async def get_session_agent_by_session_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> SessionAgent | None:
        """Return the source SessionAgent."""
        del session
        return self.source if session_id == self.source.agent_session_id else None

    async def lock_session_agent_by_id(
        self,
        session: AsyncSession,
        session_agent_id: str,
    ) -> SessionAgent | None:
        """Return the locked parent/root SessionAgent."""
        del session
        return self.parent if session_agent_id == self.parent.id else None

    async def lock_by_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> object | None:
        """Return the locked active parent AgentSession."""
        del session
        if session_id != self.parent.agent_session_id:
            return None
        return SimpleNamespace(status=AgentSessionStatus.ACTIVE)


class _AgentMailboxService:
    """AgentMailboxService test double."""

    def __init__(self) -> None:
        self.run: AgentRunState | None = None
        self.content: str | None = None

    async def enqueue_terminal_result(
        self,
        session: AsyncSession,
        *,
        source: SessionAgent,
        target: SessionAgent,
        run: AgentRunState,
        content: str,
    ) -> object:
        """Capture the terminal result projection."""
        del session, source, target
        self.run = run
        self.content = content
        return SimpleNamespace(id="mailbox-item-001")


def _session_agent(
    *,
    session_agent_id: str,
    agent_session_id: str,
    kind: SessionAgentKind,
    name: str,
    path: str,
    root_session_agent_id: str,
    parent_session_agent_id: str | None,
) -> SessionAgent:
    """Create a SessionAgent test projection."""
    now = datetime.now(UTC)
    return SessionAgent(
        id=session_agent_id,
        context_id="context-001",
        root_session_agent_id=root_session_agent_id,
        agent_session_id=agent_session_id,
        kind=kind,
        name=name,
        path=path,
        agent_type="default",
        parent_session_agent_id=parent_session_agent_id,
        last_task_message=None,
        last_message_at=None,
        parent_observed_run_index=None,
        parent_observed_event_id=None,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_user_stop_converges_interrupted_run_before_parent_delivery() -> None:
    """User Stop produces a stopped parent result after engine interruption."""
    parent = _session_agent(
        session_agent_id="parent-agent",
        agent_session_id="parent-session",
        kind=SessionAgentKind.ROOT,
        name="root",
        path="/root",
        root_session_agent_id="parent-agent",
        parent_session_agent_id=None,
    )
    source = _session_agent(
        session_agent_id="child-agent",
        agent_session_id="child-session",
        kind=SessionAgentKind.SUBAGENT,
        name="child",
        path="/root/child",
        root_session_agent_id=parent.id,
        parent_session_agent_id=parent.id,
    )
    now = datetime.now(UTC)
    run_repository = _AgentRunRepository(
        AgentRunState(
            id="11111111111111111111111111111111",
            session_id=source.agent_session_id,
            run_index=1,
            phase=AgentRunPhase.IDLE,
            status=AgentRunStatus.INTERRUPTED,
            parent_agent_run_id=None,
            terminal_result_event_id="22222222222222222222222222222222",
            terminal_result_message="partial output",
            parent_result_delivery_state=None,
            parent_result_mailbox_item_id=None,
            parent_result_enqueued_at=None,
            created_at=now,
            started_at=now,
            model_call_started_at=None,
            ended_at=now,
            updated_at=now,
        )
    )
    mailbox_service = _AgentMailboxService()
    coordinator = TerminalRunFinalizationCoordinator(
        session_manager=cast(SessionManager[AsyncSession], object()),
        agent_run_repository=cast(AgentRunRepository, run_repository),
        agent_session_repository=cast(
            AgentSessionRepository,
            _AgentSessionRepository(source, parent),
        ),
        agent_mailbox_service=cast(AgentMailboxService, mailbox_service),
    )

    outcome = await coordinator.finalize_run_in_session(
        cast(AsyncSession, object()),
        run_id=run_repository.run.id,
    )

    assert outcome.disposition is TerminalDeliveryDisposition.ENQUEUED
    assert mailbox_service.run is not None
    assert mailbox_service.run.status is AgentRunStatus.STOPPED
    assert mailbox_service.run.terminal_result_event_id is None
    assert mailbox_service.run.terminal_result_message is None
    assert mailbox_service.content == "The agent run was stopped."
