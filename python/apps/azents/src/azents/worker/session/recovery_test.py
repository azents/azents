"""StuckSessionRecovery tests."""

import datetime
from contextlib import AbstractAsyncContextManager
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import SessionBroker, SessionWakeUp
from azents.core.enums import AgentRuntimeRunState
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.worker.session.lifecycle import SessionLifecycleService
from azents.worker.session.recovery import StuckSessionRecovery


class _SessionScope(AbstractAsyncContextManager[AsyncSession]):
    """DB session context for tests."""

    async def __aenter__(self) -> AsyncSession:
        """Return test session."""
        return cast(AsyncSession, object())

    async def __aexit__(self, *exc_info: object) -> None:
        """No resources to clean up."""


class _SessionManager:
    """session manager for tests."""

    def __call__(self) -> _SessionScope:
        """Return new session scope."""
        return _SessionScope()


class _AgentRuntimeRepository(AgentRuntimeRepository):
    """AgentRuntimeRepository test double."""

    def __init__(self, runtimes: list[AgentRuntime]) -> None:
        self.runtimes = runtimes
        self.find_calls: list[tuple[datetime.timedelta, int]] = []

    async def find_stuck_running(
        self,
        session: AsyncSession,
        *,
        stale_threshold: datetime.timedelta,
        limit: int,
    ) -> list[AgentRuntime]:
        """Record stuck session fetch request and return specified result."""
        del session
        self.find_calls.append((stale_threshold, limit))
        return self.runtimes


class _Broker:
    """SessionBroker test double."""

    def __init__(self) -> None:
        self.sent_messages: list[SessionWakeUp] = []

    async def send_message(self, message: SessionWakeUp) -> None:
        """Record sent wake-up message."""
        self.sent_messages.append(message)


class _SessionLifecycle:
    """SessionLifecycleService test double."""

    def __init__(self) -> None:
        self.running_session_ids: list[str] = []

    async def mark_session_running(self, session_id: str) -> None:
        """Record session id for RUNNING transition request."""
        self.running_session_ids.append(session_id)


def _runtime(
    *,
    session_id: str | None = "session-001",
    agent_id: str = "agent-001",
    workspace_id: str = "workspace-001",
) -> AgentRuntime:
    """Create AgentRuntime for tests."""
    now = datetime.datetime.now(datetime.UTC)
    return AgentRuntime(
        id="runtime-001",
        workspace_id=workspace_id,
        agent_id=agent_id,
        current_session_id=session_id,
        run_state=AgentRuntimeRunState.RUNNING,
        run_heartbeat_at=now - datetime.timedelta(minutes=10),
        pending_command_id=None,
        pending_command_name=None,
        pending_command_payload=None,
        pending_command_user_id=None,
        pending_command_created_at=None,
        stop_requested_at=None,
        stop_requested_by=None,
        stop_request_id=None,
        created_at=now,
        updated_at=now,
    )


def _recovery(
    *,
    repository: _AgentRuntimeRepository,
    broker: _Broker,
    lifecycle: _SessionLifecycle,
    stale_threshold: datetime.timedelta = datetime.timedelta(seconds=5),
    limit: int = 7,
) -> StuckSessionRecovery:
    """Create StuckSessionRecovery under test."""
    return StuckSessionRecovery(
        broker=cast(SessionBroker, broker),
        session_manager=cast(Any, _SessionManager()),
        agent_runtime_repository=repository,
        session_lifecycle=cast(SessionLifecycleService, lifecycle),
        stale_threshold=stale_threshold,
        limit=limit,
        interval=datetime.timedelta(seconds=60),
    )


@pytest.mark.asyncio
async def test_recover_once_enqueues_resume_for_stuck_sessions() -> None:
    """stuck RUNNING session is marked running again, then re-enqueued as RESUME."""
    repository = _AgentRuntimeRepository(
        [_runtime(session_id="session-001", agent_id="agent-001")]
    )
    broker = _Broker()
    lifecycle = _SessionLifecycle()

    await _recovery(
        repository=repository,
        broker=broker,
        lifecycle=lifecycle,
    ).recover_once()

    assert repository.find_calls == [(datetime.timedelta(seconds=5), 7)]
    assert lifecycle.running_session_ids == ["session-001"]
    assert len(broker.sent_messages) == 1
    message = broker.sent_messages[0]
    assert message.agent_id == "agent-001"
    assert message.session_id == "session-001"
    assert message.user_id is None
    assert message.workspace_id == "workspace-001"


@pytest.mark.asyncio
async def test_recover_once_continues_after_record_failure() -> None:
    """One stuck record recovery failure does not block next record recovery."""
    repository = _AgentRuntimeRepository(
        [
            _runtime(session_id=None, agent_id="agent-bad"),
            _runtime(session_id="session-002", agent_id="agent-002"),
        ]
    )
    broker = _Broker()
    lifecycle = _SessionLifecycle()

    await _recovery(
        repository=repository,
        broker=broker,
        lifecycle=lifecycle,
    ).recover_once()

    assert lifecycle.running_session_ids == ["session-002"]
    assert [message.session_id for message in broker.sent_messages] == ["session-002"]
