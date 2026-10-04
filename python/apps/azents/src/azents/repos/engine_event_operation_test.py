"""Completed Event Engine operation tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentRunStatus, EventKind
from azents.engine.events.types import Event
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.engine_event_contracts import (
    AgentRunCreateRepository,
    SessionHeadRepository,
    TranscriptRepository,
)
from azents.repos.engine_event_operation import EngineEventOperationRepository


async def test_event_operations_complete_their_sessions_before_returning() -> None:
    """Event Engine results return only after their repository transactions close."""
    _raw_session = AsyncMock(spec=AsyncSession)
    session = ReadWriteSession(_raw_session)
    transaction_active = False

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[WriteSession]:
        nonlocal transaction_active
        transaction_active = True
        try:
            yield session
        finally:
            transaction_active = False

    run_repository = AsyncMock(spec=AgentRunCreateRepository)
    agent_session_repository = AsyncMock(spec=AgentSessionRepository)
    session_head_repository = AsyncMock(spec=SessionHeadRepository)
    transcript_repository = AsyncMock(spec=TranscriptRepository)
    event = AsyncMock(spec=Event)
    run_state = SimpleNamespace(status=AgentRunStatus.RUNNING)

    async def get_agent_session(
        current_session: WriteSession,
        session_id: str,
    ) -> object:
        assert transaction_active
        assert current_session is session
        assert session_id == "session-1"
        return object()

    async def append_event(
        current_session: WriteSession,
        create: EventCreate,
    ) -> Event:
        assert transaction_active
        assert current_session is session
        assert create.kind is EventKind.SYSTEM_ERROR
        return event

    async def get_session_head(
        current_session: WriteSession,
        session_id: str,
    ) -> object:
        assert transaction_active
        assert current_session is session
        assert session_id == "session-1"
        return SimpleNamespace(model_input_head_event_id="event-head")

    async def list_transcript(
        current_session: WriteSession,
        session_id: str,
        *,
        head_event_id: str | None,
    ) -> list[Event]:
        assert transaction_active
        assert current_session is session
        assert session_id == "session-1"
        assert head_event_id == "event-head"
        return []

    async def get_run(
        current_session: WriteSession,
        run_id: str,
    ) -> object:
        assert transaction_active
        assert current_session is session
        assert run_id == "run-1"
        return run_state

    agent_session_repository.get_by_id.side_effect = get_agent_session
    transcript_repository.append.side_effect = append_event
    session_head_repository.get_by_id.side_effect = get_session_head
    transcript_repository.list_for_model_input.side_effect = list_transcript
    run_repository.get_by_id.side_effect = get_run
    repository = EngineEventOperationRepository(
        session_manager=session_manager,
        run_repository=run_repository,
        agent_session_repository=agent_session_repository,
        session_head_repository=session_head_repository,
        transcript_repository=transcript_repository,
    )

    assert (
        await repository.append_system_error(
            session_id="session-1",
            content="error",
        )
        is event
    )
    assert not transaction_active

    assert await repository.prepare_compaction(session_id="session-1") == []
    assert not transaction_active

    preparation = await repository.prepare_run(
        session_id="session-1",
        run_id="run-1",
        user_messages=[],
    )
    assert preparation.user_message_events == []
    assert preparation.run_state is run_state
    assert not transaction_active

    assert (
        await repository.append_user_messages(
            session_id="session-1",
            user_messages=[],
        )
        == []
    )
    assert not transaction_active
