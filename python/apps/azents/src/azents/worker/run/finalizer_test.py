"""Failed-run finalizer tests."""

import datetime
from contextlib import AbstractAsyncContextManager
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import PublishedEvent
from azents.core.enums import AgentRunStatus, EventKind
from azents.engine.events.engine_events import RunComplete
from azents.engine.events.types import Event, RunMarkerPayload, SystemErrorPayload
from azents.engine.run.failure import FailedRunAttempt, FailedRunRetryState
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.worker.run.finalizer import (
    FailedRunErrorFinalizer,
    FailedRunFinalizationInput,
)
from azents.worker.session.lifecycle import SessionLifecycleService


class _SessionScope(AbstractAsyncContextManager[AsyncSession]):
    """DB session scope test double."""

    async def __aenter__(self) -> AsyncSession:
        """Return a dummy DB session."""
        return cast(AsyncSession, object())

    async def __aexit__(self, *exc_info: object) -> None:
        """No resources to clean up."""


class _SessionManager:
    """SessionManager test double."""

    def __call__(self) -> _SessionScope:
        """Return a new session scope."""
        return _SessionScope()


class _TranscriptRepository:
    """EventTranscriptRepository test double."""

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


class _AgentRunRepository:
    """AgentRunRepository test double."""

    def __init__(self) -> None:
        self.terminal_calls: list[tuple[str, AgentRunStatus, str | None]] = []

    async def mark_terminal_if_running(
        self,
        session: AsyncSession,
        run_id: str,
        status: AgentRunStatus,
        *,
        ended_at: datetime.datetime,
        last_completed_event_id: str | None = None,
    ) -> None:
        """Record terminal transition request."""
        del session, ended_at
        self.terminal_calls.append((run_id, status, last_completed_event_id))


class _SessionLifecycle:
    """SessionLifecycleService test double."""

    def __init__(self) -> None:
        self.cleared_session_ids: list[str] = []

    async def clear_session_activity(self, session_id: str) -> None:
        """Record session activity clear request."""
        self.cleared_session_ids.append(session_id)


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
            attempt_number=10,
            occurred_at=now,
        ),
        max_retries=10,
        backoff_seconds=60,
        next_retry_at=now + datetime.timedelta(seconds=60),
    )


@pytest.mark.asyncio
async def test_failed_run_finalizer_appends_error_marker_and_run_complete() -> None:
    """Finalizer promotes latest retry state to durable failed-run output."""
    transcript_repository = _TranscriptRepository()
    agent_run_repository = _AgentRunRepository()
    lifecycle = _SessionLifecycle()
    dispatched: list[tuple[str, PublishedEvent]] = []
    finalizer = FailedRunErrorFinalizer(
        session_manager=cast(SessionManager[AsyncSession], _SessionManager()),
        event_transcript_repository=cast(
            EventTranscriptRepository,
            transcript_repository,
        ),
        agent_run_repository=cast(AgentRunRepository, agent_run_repository),
        session_lifecycle=cast(SessionLifecycleService, lifecycle),
    )

    async def dispatch_event(session_id: str, event: PublishedEvent) -> None:
        dispatched.append((session_id, event))

    result = await finalizer.finalize(
        FailedRunFinalizationInput(
            session_id="session-001",
            run_id="run-001".rjust(32, "0"),
            user_message="temporary failure",
            retry_state=_retry_state(),
            reason="retry_exhausted",
        ),
        dispatch_event=dispatch_event,
    )

    assert [create.kind for create in transcript_repository.creates] == [
        EventKind.SYSTEM_ERROR,
        EventKind.RUN_MARKER,
    ]
    error_payload = result.error_event.payload
    assert isinstance(error_payload, SystemErrorPayload)
    assert error_payload.content == "temporary failure"
    assert error_payload.failure is not None
    assert error_payload.failure.kind == "failed_run"
    assert error_payload.failure.finalization_reason == "retry_exhausted"
    assert error_payload.failure.failed_attempt_count == 10
    marker_payload = result.run_marker.payload
    assert isinstance(marker_payload, RunMarkerPayload)
    assert marker_payload.status == "failed"
    assert agent_run_repository.terminal_calls == [
        ("run-001".rjust(32, "0"), AgentRunStatus.FAILED, result.run_marker.id)
    ]
    assert isinstance(dispatched[-1][1], RunComplete)
    assert lifecycle.cleared_session_ids == ["session-001"]
