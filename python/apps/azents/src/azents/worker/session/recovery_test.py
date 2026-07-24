"""StuckSessionRecovery tests."""

import datetime
from contextlib import AbstractAsyncContextManager
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import SessionBroker, SessionWakeUp
from azents.core.enums import (
    AgentSessionKind,
    AgentSessionRunState,
    AgentSessionStartReason,
    AgentSessionStatus,
)
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession
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


class _AgentSessionRepository(AgentSessionRepository):
    """AgentSessionRepository test double."""

    def __init__(self, sessions: list[AgentSession]) -> None:
        self.sessions = sessions
        self.find_calls: list[tuple[datetime.timedelta, int]] = []

    async def find_stuck_running(
        self,
        session: AsyncSession,
        *,
        stale_threshold: datetime.timedelta,
        limit: int,
    ) -> list[AgentSession]:
        """Record stuck session fetch request and return specified result."""
        del session
        self.find_calls.append((stale_threshold, limit))
        return self.sessions


class _Broker:
    """SessionBroker test double."""

    def __init__(self) -> None:
        self.sent_messages: list[SessionWakeUp] = []

    async def send_message(self, message: SessionWakeUp) -> None:
        """Record sent wake-up message."""
        self.sent_messages.append(message)


class _SessionLifecycle:
    """SessionLifecycleService test double."""

    def __init__(self, *, fail_for: str | None = None) -> None:
        self.fail_for = fail_for
        self.running_session_ids: list[str] = []

    async def mark_session_running(self, session_id: str) -> None:
        """Record session id for RUNNING transition request."""
        if session_id == self.fail_for:
            raise RuntimeError("mark failed")
        self.running_session_ids.append(session_id)


def _agent_session(
    *,
    session_id: str = "session-001",
    agent_id: str = "agent-001",
    workspace_id: str = "workspace-001",
    session_kind: AgentSessionKind = AgentSessionKind.ROOT,
) -> AgentSession:
    """Create AgentSession for tests."""
    now = datetime.datetime.now(datetime.UTC)
    return AgentSession(
        owner_generation=0,
        inference_state=None,
        id=session_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        handle="test-session-handle",
        session_kind=session_kind,
        status=AgentSessionStatus.ACTIVE,
        start_reason=AgentSessionStartReason.INITIAL,
        title=None,
        title_source=None,
        title_generated_at=None,
        title_generation_event_id=None,
        last_user_input_at=now,
        end_reason=None,
        started_at=now,
        lifecycle_started_at=None,
        run_state=AgentSessionRunState.RUNNING,
        run_heartbeat_at=now - datetime.timedelta(minutes=10),
        pending_command_id=None,
        pending_command_name=None,
        pending_command_payload=None,
        pending_command_requester_user_id=None,
        pending_command_created_at=None,
        stop_requested_at=None,
        stop_requester_user_id=None,
        stop_request_id=None,
        ended_at=None,
        created_at=now,
        updated_at=now,
    )


def _recovery(
    *,
    repository: _AgentSessionRepository,
    broker: _Broker,
    lifecycle: _SessionLifecycle,
    stale_threshold: datetime.timedelta = datetime.timedelta(seconds=5),
    limit: int = 7,
) -> StuckSessionRecovery:
    """Create StuckSessionRecovery under test."""
    return StuckSessionRecovery(
        broker=cast(SessionBroker, broker),
        session_manager=cast(Any, _SessionManager()),
        agent_session_repository=repository,
        session_lifecycle=cast(SessionLifecycleService, lifecycle),
        stale_threshold=stale_threshold,
        limit=limit,
        interval=datetime.timedelta(seconds=60),
    )


@pytest.mark.asyncio
async def test_recover_once_enqueues_resume_for_stuck_sessions() -> None:
    """stuck RUNNING session is marked running again, then re-enqueued as RESUME."""
    repository = _AgentSessionRepository(
        [_agent_session(session_id="session-001", agent_id="agent-001")]
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
    assert broker.sent_messages == [SessionWakeUp(session_id="session-001")]


@pytest.mark.asyncio
async def test_recover_once_continues_after_record_failure() -> None:
    """One stuck record recovery failure does not block next record recovery."""
    repository = _AgentSessionRepository(
        [
            _agent_session(session_id="session-bad", agent_id="agent-bad"),
            _agent_session(session_id="session-002", agent_id="agent-002"),
        ]
    )
    broker = _Broker()
    lifecycle = _SessionLifecycle(fail_for="session-bad")

    await _recovery(
        repository=repository,
        broker=broker,
        lifecycle=lifecycle,
    ).recover_once()

    assert lifecycle.running_session_ids == ["session-002"]
    assert [message.session_id for message in broker.sent_messages] == ["session-002"]


@pytest.mark.asyncio
async def test_recover_once_treats_root_and_subagent_sessions_independently() -> None:
    """Root and subagent stuck sessions are recovered as independent sessions."""
    repository = _AgentSessionRepository(
        [
            _agent_session(session_id="root-session", agent_id="agent-001"),
            _agent_session(
                session_id="child-session",
                agent_id="agent-001",
                session_kind=AgentSessionKind.SUBAGENT,
            ),
        ]
    )
    broker = _Broker()
    lifecycle = _SessionLifecycle()

    await _recovery(
        repository=repository,
        broker=broker,
        lifecycle=lifecycle,
    ).recover_once()

    assert lifecycle.running_session_ids == ["root-session", "child-session"]
    assert [message.session_id for message in broker.sent_messages] == [
        "root-session",
        "child-session",
    ]
