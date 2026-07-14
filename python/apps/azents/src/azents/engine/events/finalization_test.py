"""Failed-run event-store tests."""

import datetime
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentRunStatus, EventKind
from azents.engine.events.finalization import FailedRunEventStore
from azents.engine.events.protocols import TranscriptRepository
from azents.engine.events.types import Event, RunMarkerPayload, SystemErrorPayload
from azents.engine.run.failure import FailedRunAttempt, FailedRunRetryState
from azents.repos.agent_execution import AgentRunNotActiveError, AgentRunRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_session import AgentSessionRepository


class _TranscriptRepository:
    """TranscriptRepository test double."""

    def __init__(self) -> None:
        self.creates: list[EventCreate] = []

    async def append(self, session: AsyncSession, create: EventCreate) -> Event:
        """Record event creation and return a matching event."""
        del session
        self.creates.append(create)
        return Event(
            id=f"{len(self.creates):032d}",
            session_id=create.session_id,
            kind=create.kind,
            payload=_payload_from_create(create),
            external_id=create.external_id,
            created_at=datetime.datetime.now(datetime.UTC),
        )


class _RunRepository:
    """RunStateRepository test double."""

    def __init__(self, lock_order: list[str]) -> None:
        self.lock_order = lock_order
        self.run = SimpleNamespace(
            id="run-001".rjust(32, "0"),
            session_id="session-001",
            status=AgentRunStatus.RUNNING,
        )
        self.terminal_calls: list[
            tuple[str, AgentRunStatus, str | None, str | None, str | None]
        ] = []

    async def lock_by_id(
        self,
        session: AsyncSession,
        run_id: str,
    ) -> object:
        """Record the row-lock order and return the current Run."""
        del session, run_id
        self.lock_order.append("run")
        return self.run

    async def mark_terminal_if_running(
        self,
        session: AsyncSession,
        run_id: str,
        status: AgentRunStatus,
        *,
        ended_at: datetime.datetime,
        last_completed_event_id: str | None = None,
        terminal_result_event_id: str | None = None,
        terminal_result_message: str | None = None,
    ) -> object:
        """Record terminal transition request."""
        del session, ended_at
        self.terminal_calls.append(
            (
                run_id,
                status,
                last_completed_event_id,
                terminal_result_event_id,
                terminal_result_message,
            )
        )
        self.run = SimpleNamespace(
            id=run_id,
            session_id=self.run.session_id,
            status=status,
        )
        return self.run


class _AgentSessionRepository:
    """AgentSessionRepository test double."""

    def __init__(self, lock_order: list[str]) -> None:
        self.lock_order = lock_order

    async def lock_by_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> object:
        """Record the row-lock order and return the requested Session."""
        del session, session_id
        self.lock_order.append("session")
        return object()


class _Session:
    """Dummy session."""


def _payload_from_create(create: EventCreate) -> SystemErrorPayload | RunMarkerPayload:
    if create.kind == EventKind.SYSTEM_ERROR:
        return SystemErrorPayload.model_validate(create.payload)
    if create.kind == EventKind.RUN_MARKER:
        return RunMarkerPayload.model_validate(create.payload)
    raise AssertionError("unexpected event kind")


def _retry_state() -> FailedRunRetryState:
    now = datetime.datetime.now(datetime.UTC)
    return FailedRunRetryState.from_attempt(
        FailedRunAttempt(
            user_message="temporary failure",
            internal_message="RuntimeError('temporary failure')",
            error_type="RuntimeError",
            source="engine",
            visibility="internal",
            attempt_number=3,
            occurred_at=now,
        ),
        max_retries=10,
        backoff_seconds=4,
        next_retry_at=now + datetime.timedelta(seconds=4),
    )


@pytest.mark.asyncio
async def test_failed_run_event_store_appends_terminal_failed_run() -> None:
    """FailedRunEventStore owns durable failed-run appends and run transition."""
    lock_order: list[str] = []
    transcript_repo = _TranscriptRepository()
    run_repo = _RunRepository(lock_order)
    session_repo = _AgentSessionRepository(lock_order)
    store = FailedRunEventStore(
        transcript_repo=cast(TranscriptRepository, transcript_repo),
        run_repo=cast(AgentRunRepository, run_repo),
        session_repo=cast(AgentSessionRepository, session_repo),
    )

    result = await store.append_terminal_failed_run(
        cast(AsyncSession, _Session()),
        session_id="session-001",
        run_id="run-001".rjust(32, "0"),
        user_message="temporary failure",
        retry_state=_retry_state(),
        reason="retry_exhausted",
        action_hint="try again later",
    )

    assert [create.kind for create in transcript_repo.creates] == [
        EventKind.SYSTEM_ERROR,
        EventKind.RUN_MARKER,
    ]
    assert transcript_repo.creates[0].external_id == (
        f"failed-run:{'run-001'.rjust(32, '0')}:system-error"
    )
    assert transcript_repo.creates[1].external_id == (
        f"failed-run:{'run-001'.rjust(32, '0')}:run-marker"
    )
    error_payload = result.error_event.payload
    assert isinstance(error_payload, SystemErrorPayload)
    assert error_payload.content == "temporary failure"
    assert error_payload.failure is not None
    assert error_payload.failure.finalization_reason == "retry_exhausted"
    assert error_payload.failure.action_hint == "try again later"
    assert len(error_payload.failure.attempts) == 1
    assert error_payload.failure.attempts[0].user_message == "temporary failure"
    marker_payload = result.run_marker.payload
    assert isinstance(marker_payload, RunMarkerPayload)
    assert marker_payload.run_id == "run-001".rjust(32, "0")
    assert marker_payload.status == "failed"
    assert run_repo.terminal_calls == [
        (
            "run-001".rjust(32, "0"),
            AgentRunStatus.FAILED,
            result.run_marker.id,
            result.error_event.id,
            "temporary failure",
        )
    ]
    assert lock_order == ["session", "run"]


@pytest.mark.asyncio
async def test_failed_run_event_store_does_not_append_after_stop_wins() -> None:
    """A terminal winner fences stale failed history before any append."""
    lock_order: list[str] = []
    transcript_repo = _TranscriptRepository()
    run_repo = _RunRepository(lock_order)
    run_repo.run = SimpleNamespace(
        id="run-001".rjust(32, "0"),
        session_id="session-001",
        status=AgentRunStatus.STOPPED,
    )
    store = FailedRunEventStore(
        transcript_repo=cast(TranscriptRepository, transcript_repo),
        run_repo=cast(AgentRunRepository, run_repo),
        session_repo=cast(
            AgentSessionRepository,
            _AgentSessionRepository(lock_order),
        ),
    )

    with pytest.raises(AgentRunNotActiveError) as error:
        await store.append_terminal_failed_run(
            cast(AsyncSession, _Session()),
            session_id="session-001",
            run_id="run-001".rjust(32, "0"),
            user_message="temporary failure",
            retry_state=_retry_state(),
            reason="retry_exhausted",
        )

    assert error.value.status == AgentRunStatus.STOPPED
    assert lock_order == ["session", "run"]
    assert transcript_repo.creates == []
    assert run_repo.terminal_calls == []
