"""Failed-run finalizer tests."""

import datetime
from contextlib import AbstractAsyncContextManager
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import PublishedEvent
from azents.core.enums import EventKind
from azents.engine.events.engine_events import RunComplete
from azents.engine.events.finalization import (
    FailedRunEventStore,
    FailedRunEventStoreResult,
)
from azents.engine.events.types import Event, RunMarkerPayload, SystemErrorPayload
from azents.engine.run.failure import (
    FailedRunAttempt,
    FailedRunFailureMetadata,
    FailedRunFinalizationReason,
    FailedRunRetryState,
)
from azents.rdb.session import SessionManager
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


class _FailedRunEventStore:
    """FailedRunEventStore test double."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.creates: list[EventCreate] = []

    async def append_terminal_failed_run(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        run_id: str,
        user_message: str,
        retry_state: FailedRunRetryState,
        reason: FailedRunFinalizationReason,
        action_hint: str | None = None,
    ) -> FailedRunEventStoreResult:
        """Record finalization request and return matching events."""
        del session
        self.calls.append(
            {
                "session_id": session_id,
                "run_id": run_id,
                "user_message": user_message,
                "retry_state": retry_state,
                "reason": reason,
                "action_hint": action_hint,
            }
        )
        error_create = EventCreate(
            session_id=session_id,
            kind=EventKind.SYSTEM_ERROR,
            payload=SystemErrorPayload(
                content=user_message,
                severity="error",
                recoverable=True,
                failure=FailedRunFailureMetadata.from_retry_state(
                    retry_state,
                    finalization_reason=reason,
                    action_hint=action_hint,
                ),
            ).model_dump(mode="json", exclude_none=True),
            external_id=f"failed-run:{run_id}:system-error",
        )
        marker_create = EventCreate(
            session_id=session_id,
            kind=EventKind.RUN_MARKER,
            payload=RunMarkerPayload(
                run_id=run_id,
                status="failed",
                error=user_message,
            ).model_dump(mode="json", exclude_none=True),
            external_id=f"failed-run:{run_id}:run-marker",
        )
        self.creates.extend([error_create, marker_create])
        return FailedRunEventStoreResult(
            error_event=Event(
                id="1".rjust(32, "0"),
                session_id=session_id,
                kind=EventKind.SYSTEM_ERROR,
                payload=_payload_from_create(error_create),
                external_id=error_create.external_id,
                created_at=datetime.datetime.now(datetime.UTC),
            ),
            run_marker=Event(
                id="2".rjust(32, "0"),
                session_id=session_id,
                kind=EventKind.RUN_MARKER,
                payload=_payload_from_create(marker_create),
                external_id=marker_create.external_id,
                created_at=datetime.datetime.now(datetime.UTC),
            ),
        )


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
    event_store = _FailedRunEventStore()
    lifecycle = _SessionLifecycle()
    dispatched: list[tuple[str, PublishedEvent]] = []
    finalizer = FailedRunErrorFinalizer(
        session_manager=cast(SessionManager[AsyncSession], _SessionManager()),
        event_store=cast(FailedRunEventStore, event_store),
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

    assert [create.kind for create in event_store.creates] == [
        EventKind.SYSTEM_ERROR,
        EventKind.RUN_MARKER,
    ]
    assert event_store.calls[0]["reason"] == "retry_exhausted"
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
    terminal_event = dispatched[-1][1]
    assert isinstance(terminal_event, RunComplete)
    assert terminal_event.run_id == "run-001".rjust(32, "0")
    assert lifecycle.cleared_session_ids == ["session-001"]
