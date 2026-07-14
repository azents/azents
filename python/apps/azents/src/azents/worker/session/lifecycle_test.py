"""SessionLifecycleService tests."""

from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import SessionBroker, SessionOwnershipLostError
from azents.core.enums import AgentRunPhase, AgentRunStatus
from azents.engine.events.types import AgentRunState
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession
from azents.repos.input_buffer.repository import InputBufferRepository
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

    def __init__(
        self,
        *,
        heartbeat_error: Exception | None = None,
        order: list[str] | None = None,
    ) -> None:
        self.owner_heartbeat_session_ids: list[str] = []
        self.heartbeat_error = heartbeat_error
        self.order = order

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
    ) -> None:
        """This test does not set broker activity."""
        del session_id, run_id, phase

    async def renew_session_owner_heartbeat(self, session_id: str) -> None:
        """Record owner heartbeat renewal."""
        if self.order is not None:
            self.order.append("redis")
        self.owner_heartbeat_session_ids.append(session_id)
        if self.heartbeat_error is not None:
            raise self.heartbeat_error


class _AgentSessionRepository:
    """AgentSessionRepository test double."""

    def __init__(
        self,
        *,
        heartbeat_error: Exception | None = None,
        heartbeat_updated: bool = True,
        order: list[str] | None = None,
    ) -> None:
        self.idle_session_ids: list[str] = []
        self.heartbeat_error = heartbeat_error
        self.heartbeat_updated = heartbeat_updated
        self.heartbeat_calls: list[tuple[str, int]] = []
        self.order = order

    async def lock_by_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> AgentSession:
        """Return an existing locked Session marker."""
        del session, agent_session_id
        return cast(AgentSession, object())

    async def mark_idle(self, session: AsyncSession, runtime_id: str) -> None:
        """Record idle transition."""
        del session
        self.idle_session_ids.append(runtime_id)

    async def heartbeat_running(
        self,
        session: AsyncSession,
        session_id: str,
        *,
        expected_owner_generation: int,
    ) -> bool:
        """Raise the configured DB heartbeat failure, if any."""
        del session
        if self.order is not None:
            self.order.append("db")
        self.heartbeat_calls.append((session_id, expected_owner_generation))
        if self.heartbeat_error is not None:
            raise self.heartbeat_error
        return self.heartbeat_updated


class _InputBufferRepository:
    """InputBufferRepository test double."""

    def __init__(self, pending: bool) -> None:
        self.pending = pending

    async def list_for_flush(
        self,
        session: AsyncSession,
        session_id: str,
        *,
        limit: int | None = None,
    ) -> list[object]:
        """Return the configured queue state at the idle boundary."""
        del session, session_id, limit
        return [object()] if self.pending else []


class _AgentRunRepository:
    """AgentRunRepository test double."""

    def __init__(
        self,
        running_run: AgentRunState | None,
        *,
        activated_run: AgentRunState | None = None,
        terminal_error: Exception | None = None,
    ) -> None:
        self.running_run = running_run
        self.activated_run = activated_run
        self.terminal_error = terminal_error
        self.terminal_session_ids: list[str] = []
        self.activation_run_ids: list[str] = []

    async def get_active_by_session_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> AgentRunState | None:
        """Return test-specified active run."""
        del session, session_id
        return self.running_run

    async def activate_pending(
        self,
        session: AsyncSession,
        *,
        run_id: str,
        activated_at: datetime,
    ) -> AgentRunState:
        """Return the test inherited run selected for activation."""
        del session, activated_at
        self.activation_run_ids.append(run_id)
        if self.activated_run is None:
            raise AssertionError("Activation test run was not configured")
        return self.activated_run

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

    async def mark_terminal_if_running(
        self,
        session: AsyncSession,
        run_id: str,
        status: AgentRunStatus,
        *,
        ended_at: datetime,
    ) -> AgentRunState | None:
        """Raise the configured terminal persistence failure, if any."""
        del session, run_id, status, ended_at
        if self.terminal_error is not None:
            raise self.terminal_error
        return self.running_run


def _running_run() -> AgentRunState:
    """Create a running AgentRunState."""
    now = datetime.now(UTC)
    return AgentRunState(
        id="1123456789abcdef0123456789abcdef",
        session_id="session-001",
        run_index=1,
        phase=AgentRunPhase.EXECUTING_TOOLS,
        status=AgentRunStatus.RUNNING,
        parent_agent_run_id=None,
        active_tool_calls=[],
        created_at=now,
        started_at=now,
        model_call_started_at=None,
        updated_at=now,
    )


def _service(
    *,
    agent_run_repository: _AgentRunRepository,
    agent_session_repository: _AgentSessionRepository,
    pending_input: bool,
    broker: _Broker | None = None,
) -> SessionLifecycleService:
    """Create SessionLifecycleService with test doubles."""
    return SessionLifecycleService(
        broker=cast(SessionBroker, broker or _Broker()),
        session_manager=cast(SessionManager[AsyncSession], _SessionManager()),
        agent_session_repository=cast(
            AgentSessionRepository,
            agent_session_repository,
        ),
        agent_run_repository=cast(AgentRunRepository, agent_run_repository),
        input_buffer_repository=cast(
            InputBufferRepository,
            _InputBufferRepository(pending_input),
        ),
    )


@pytest.mark.asyncio
async def test_mark_session_idle_rejects_active_agent_run() -> None:
    """Active AgentRun blocks Runtime idle transition."""
    agent_run_repository = _AgentRunRepository(_running_run())
    agent_session_repository = _AgentSessionRepository()
    service = _service(
        agent_run_repository=agent_run_repository,
        agent_session_repository=agent_session_repository,
        pending_input=False,
    )

    marked_idle = await service.mark_session_idle("session-001")

    assert not marked_idle
    assert agent_session_repository.idle_session_ids == []
    assert agent_run_repository.terminal_session_ids == []


@pytest.mark.asyncio
async def test_mark_session_idle_rechecks_queue_under_session_lock() -> None:
    """A concurrently accepted input prevents the empty boundary from idling."""
    agent_run_repository = _AgentRunRepository(None)
    agent_session_repository = _AgentSessionRepository()
    service = _service(
        agent_run_repository=agent_run_repository,
        agent_session_repository=agent_session_repository,
        pending_input=True,
    )

    marked_idle = await service.mark_session_idle("session-001")

    assert not marked_idle
    assert agent_session_repository.idle_session_ids == []


@pytest.mark.asyncio
async def test_mark_session_idle_allows_terminal_run_boundary() -> None:
    """Runtime becomes idle only when there is no running AgentRun."""
    agent_run_repository = _AgentRunRepository(None)
    agent_session_repository = _AgentSessionRepository()
    service = _service(
        agent_run_repository=agent_run_repository,
        agent_session_repository=agent_session_repository,
        pending_input=False,
    )

    marked_idle = await service.mark_session_idle("session-001")

    assert marked_idle
    assert agent_session_repository.idle_session_ids == ["session-001"]
    assert agent_run_repository.terminal_session_ids == []


@pytest.mark.asyncio
async def test_activate_pending_rejects_session_mismatch() -> None:
    """Pending activation cannot cross the requested session boundary."""
    activated_run = _running_run().model_copy(update={"session_id": "session-002"})
    agent_run_repository = _AgentRunRepository(
        None,
        activated_run=activated_run,
    )
    service = _service(
        agent_run_repository=agent_run_repository,
        agent_session_repository=_AgentSessionRepository(),
        pending_input=False,
    )

    with pytest.raises(ValueError, match="AgentRun session mismatch"):
        await service.activate_pending_agent_run(
            "session-001",
            run_id=activated_run.id,
        )

    assert agent_run_repository.activation_run_ids == [activated_run.id]


@pytest.mark.asyncio
async def test_terminal_transition_propagates_db_failure() -> None:
    """A failed terminal write cannot be reported to the executor as persisted."""
    error = RuntimeError("terminal write failed")
    service = _service(
        agent_run_repository=_AgentRunRepository(None, terminal_error=error),
        agent_session_repository=_AgentSessionRepository(),
        pending_input=False,
    )

    with pytest.raises(RuntimeError, match="terminal write failed"):
        await service.mark_agent_run_terminal_if_running(
            "session-001",
            run_id="run-001",
            status=AgentRunStatus.COMPLETED,
        )


@pytest.mark.asyncio
async def test_terminal_transition_rejects_run_from_another_session() -> None:
    """A session lifecycle call cannot terminalize another session's Run."""
    other_session_run = _running_run().model_copy(update={"session_id": "session-002"})
    service = _service(
        agent_run_repository=_AgentRunRepository(other_session_run),
        agent_session_repository=_AgentSessionRepository(),
        pending_input=False,
    )

    with pytest.raises(ValueError, match="AgentRun not found in session"):
        await service.mark_agent_run_terminal_if_running(
            "session-001",
            run_id=other_session_run.id,
            status=AgentRunStatus.COMPLETED,
        )


@pytest.mark.asyncio
async def test_heartbeat_validates_lease_before_generation_fenced_db_write() -> None:
    """Heartbeat performs no DB write until Redis proves current ownership."""
    order: list[str] = []
    broker = _Broker(order=order)
    agent_session_repository = _AgentSessionRepository(
        heartbeat_error=RuntimeError("heartbeat write failed"),
        order=order,
    )
    service = _service(
        agent_run_repository=_AgentRunRepository(None),
        agent_session_repository=agent_session_repository,
        pending_input=False,
        broker=broker,
    )

    with pytest.raises(RuntimeError, match="heartbeat write failed"):
        await service.heartbeat_session("session-001", owner_generation=7)

    assert order == ["redis", "db"]
    assert broker.owner_heartbeat_session_ids == ["session-001"]
    assert agent_session_repository.heartbeat_calls == [("session-001", 7)]


@pytest.mark.asyncio
async def test_redis_ownership_loss_prevents_db_heartbeat() -> None:
    """A stale worker cannot refresh DB liveness after its lease was stolen."""
    order: list[str] = []
    broker = _Broker(
        heartbeat_error=SessionOwnershipLostError("session-001"),
        order=order,
    )
    agent_session_repository = _AgentSessionRepository(order=order)
    service = _service(
        agent_run_repository=_AgentRunRepository(None),
        agent_session_repository=agent_session_repository,
        pending_input=False,
        broker=broker,
    )

    with pytest.raises(SessionOwnershipLostError, match="session-001"):
        await service.heartbeat_session("session-001", owner_generation=3)

    assert order == ["redis"]
    assert agent_session_repository.heartbeat_calls == []


@pytest.mark.asyncio
async def test_redis_heartbeat_timeout_prevents_db_heartbeat() -> None:
    """An unverifiable Redis lease cannot authorize durable DB liveness."""
    order: list[str] = []
    broker = _Broker(
        heartbeat_error=TimeoutError("Redis owner check timed out"),
        order=order,
    )
    agent_session_repository = _AgentSessionRepository(order=order)
    service = _service(
        agent_run_repository=_AgentRunRepository(None),
        agent_session_repository=agent_session_repository,
        pending_input=False,
        broker=broker,
    )

    with pytest.raises(TimeoutError, match="Redis owner check timed out"):
        await service.heartbeat_session("session-001", owner_generation=3)

    assert order == ["redis"]
    assert agent_session_repository.heartbeat_calls == []


@pytest.mark.asyncio
async def test_stale_owner_generation_rejects_db_heartbeat() -> None:
    """A lease check cannot authorize a heartbeat for an obsolete generation."""
    order: list[str] = []
    broker = _Broker(order=order)
    agent_session_repository = _AgentSessionRepository(
        heartbeat_updated=False,
        order=order,
    )
    service = _service(
        agent_run_repository=_AgentRunRepository(None),
        agent_session_repository=agent_session_repository,
        pending_input=False,
        broker=broker,
    )

    with pytest.raises(SessionOwnershipLostError, match="session-001"):
        await service.heartbeat_session("session-001", owner_generation=4)

    assert order == ["redis", "db"]
    assert agent_session_repository.heartbeat_calls == [("session-001", 4)]
