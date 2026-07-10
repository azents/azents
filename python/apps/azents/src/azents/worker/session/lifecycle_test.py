"""SessionLifecycleService tests."""

from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import SessionBroker
from azents.core.enums import AgentRunPhase, AgentRunStatus
from azents.engine.events.types import ActiveToolCall, AgentRunState
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.worker.session.lifecycle import SessionLifecycleService


class _SessionScope(AbstractAsyncContextManager[AsyncSession]):
    """DB session context for tests."""

    async def __aenter__(self) -> AsyncSession:
        """Return test session."""
        return cast(AsyncSession, object())

    async def __aexit__(self, *exc_info: object) -> None:
        """No resources to clean up."""


class _SessionManager:
    """Session manager for tests."""

    def __call__(self) -> _SessionScope:
        """Return new session scope."""
        return _SessionScope()


class _Broker:
    """SessionBroker test double."""

    async def release_session_lock(self, session_id: str) -> None:
        """This test does not release broker locks."""
        del session_id

    async def clear_session_activity(self, session_id: str) -> None:
        """This test does not clear broker activity."""
        del session_id

    async def set_session_activity(
        self,
        session_id: str,
        *,
        run_id: str,
        phase: AgentRunPhase | None = None,
        active_tool_calls: Sequence[ActiveToolCall] = (),
    ) -> None:
        """This test does not set broker activity."""
        del session_id, run_id, phase, active_tool_calls

    async def renew_session_owner_heartbeat(self, session_id: str) -> None:
        """This test does not renew owner heartbeat."""
        del session_id


class _AgentSessionRepository:
    """AgentSessionRepository test double."""

    def __init__(self) -> None:
        self.idle_session_ids: list[str] = []

    async def mark_idle(self, session: AsyncSession, runtime_id: str) -> None:
        """Record idle transition."""
        del session
        self.idle_session_ids.append(runtime_id)


class _AgentRunRepository:
    """AgentRunRepository test double."""

    def __init__(
        self,
        running_run: AgentRunState | None,
        *,
        inherited_run: AgentRunState | None = None,
    ) -> None:
        self.running_run = running_run
        self.inherited_run = inherited_run
        self.terminal_session_ids: list[str] = []
        self.inherited_activation_run_ids: list[str] = []

    async def get_active_by_session_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> AgentRunState | None:
        """Return test-specified active run."""
        del session, session_id
        return self.running_run

    async def activate_inherited_pending(
        self,
        session: AsyncSession,
        *,
        run_id: str,
        activated_at: datetime,
    ) -> AgentRunState:
        """Return the test inherited run selected for activation."""
        del session, activated_at
        self.inherited_activation_run_ids.append(run_id)
        if self.inherited_run is None:
            raise AssertionError("Inherited test run was not configured")
        return self.inherited_run

    async def mark_session_running_terminal(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        status: AgentRunStatus,
        ended_at: datetime,
    ) -> None:
        """Record broad terminal transition requests."""
        del session, status, ended_at
        self.terminal_session_ids.append(session_id)


def _running_run() -> AgentRunState:
    """Create a running AgentRunState."""
    now = datetime.now(UTC)
    return AgentRunState(
        id="1123456789abcdef0123456789abcdef",
        session_id="session-001",
        run_index=1,
        phase=AgentRunPhase.EXECUTING_TOOLS,
        status=AgentRunStatus.RUNNING,
        requested_model_target_label=None,
        requested_reasoning_effort=None,
        inference_profile_source=None,
        resolved_model_selection=None,
        resolved_reasoning_effort=None,
        resolved_at=None,
        effective_context_window_tokens=None,
        effective_auto_compaction_threshold_tokens=None,
        inference_profile_failure_code=None,
        inference_profile_failure_message=None,
        parent_agent_run_id=None,
        active_tool_calls=[],
        created_at=now,
        started_at=now,
        updated_at=now,
    )


def _service(
    *,
    agent_run_repository: _AgentRunRepository,
    agent_session_repository: _AgentSessionRepository,
) -> SessionLifecycleService:
    """Create SessionLifecycleService with test doubles."""
    return SessionLifecycleService(
        broker=cast(SessionBroker, _Broker()),
        session_manager=cast(SessionManager[AsyncSession], _SessionManager()),
        agent_session_repository=cast(
            AgentSessionRepository,
            agent_session_repository,
        ),
        agent_run_repository=cast(AgentRunRepository, agent_run_repository),
        event_transcript_repository=EventTranscriptRepository(),
    )


@pytest.mark.asyncio
async def test_mark_session_idle_rejects_active_agent_run() -> None:
    """Active AgentRun blocks Runtime idle transition."""
    agent_run_repository = _AgentRunRepository(_running_run())
    agent_session_repository = _AgentSessionRepository()
    service = _service(
        agent_run_repository=agent_run_repository,
        agent_session_repository=agent_session_repository,
    )

    marked_idle = await service.mark_session_idle("session-001")

    assert not marked_idle
    assert agent_session_repository.idle_session_ids == []
    assert agent_run_repository.terminal_session_ids == []


@pytest.mark.asyncio
async def test_mark_session_idle_allows_terminal_run_boundary() -> None:
    """Runtime becomes idle only when there is no running AgentRun."""
    agent_run_repository = _AgentRunRepository(None)
    agent_session_repository = _AgentSessionRepository()
    service = _service(
        agent_run_repository=agent_run_repository,
        agent_session_repository=agent_session_repository,
    )

    marked_idle = await service.mark_session_idle("session-001")

    assert marked_idle
    assert agent_session_repository.idle_session_ids == ["session-001"]
    assert agent_run_repository.terminal_session_ids == []


@pytest.mark.asyncio
async def test_activate_inherited_pending_rejects_session_mismatch() -> None:
    """Inherited activation cannot cross the requested session boundary."""
    inherited_run = _running_run().model_copy(update={"session_id": "session-002"})
    agent_run_repository = _AgentRunRepository(
        None,
        inherited_run=inherited_run,
    )
    service = _service(
        agent_run_repository=agent_run_repository,
        agent_session_repository=_AgentSessionRepository(),
    )

    with pytest.raises(ValueError, match="AgentRun session mismatch"):
        await service.activate_inherited_pending_agent_run(
            "session-001",
            run_id=inherited_run.id,
        )

    assert agent_run_repository.inherited_activation_run_ids == [inherited_run.id]
