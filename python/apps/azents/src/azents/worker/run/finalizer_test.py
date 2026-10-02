"""Session-free failed-run facade and post-commit publication tests."""

import asyncio
import datetime

import pytest

from azents.broker.types import PublishedEvent
from azents.core.enums import EventKind
from azents.engine.events.engine_events import RunComplete
from azents.engine.events.types import Event, RunMarkerPayload, SystemErrorPayload
from azents.engine.run.failure import (
    FailedRunAttempt,
    FailedRunFailureMetadata,
    FailedRunRetryState,
)
from azents.repos.failed_run_finalization_operation import (
    FailedRunFinalization,
    FailedRunFinalizationEvents,
    FailedRunFinalizationOperationRepository,
)
from azents.repos.session_execution import CanonicalExecutionOwnerGenerationStaleError
from azents.worker.run.finalizer import (
    FailedRunErrorFinalizer,
    FailedRunFinalizationInput,
)

_RUN_ID = "run-001".rjust(32, "0")


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


def _events() -> FailedRunFinalizationEvents:
    retry_state = _retry_state()
    return FailedRunFinalizationEvents(
        error_event=Event(
            id="1".rjust(32, "0"),
            session_id="session-001",
            kind=EventKind.SYSTEM_ERROR,
            payload=SystemErrorPayload(
                content="temporary failure",
                severity="error",
                recoverable=True,
                failure=FailedRunFailureMetadata.from_retry_state(
                    retry_state,
                    finalization_reason="retry_exhausted",
                    action_hint=None,
                    model_operation=None,
                ),
            ),
            external_id=f"failed-run:{_RUN_ID}:system-error",
            created_at=datetime.datetime.now(datetime.UTC),
        ),
        run_marker=Event(
            id="2".rjust(32, "0"),
            session_id="session-001",
            kind=EventKind.RUN_MARKER,
            payload=RunMarkerPayload(
                run_id=_RUN_ID,
                status="failed",
                error="temporary failure",
            ),
            external_id=f"failed-run:{_RUN_ID}:run-marker",
            created_at=datetime.datetime.now(datetime.UTC),
        ),
    )


def _input() -> FailedRunFinalizationInput:
    return FailedRunFinalizationInput(
        session_id="session-001",
        owner_generation=1,
        run_id=_RUN_ID,
        user_message="temporary failure",
        retry_state=_retry_state(),
        reason="retry_exhausted",
        action_hint="try again later",
    )


class _Repository(FailedRunFinalizationOperationRepository):
    """Completed-operation fake; it never offers a session to the Worker."""

    def __init__(
        self,
        *,
        result: FailedRunFinalizationEvents | None,
        failure: BaseException | None,
    ) -> None:
        self.result = result
        self.failure = failure
        self.calls: list[FailedRunFinalization] = []
        self.completed = False

    async def finalize(
        self,
        input: FailedRunFinalization,
    ) -> FailedRunFinalizationEvents | None:
        self.calls.append(input)
        if self.failure is not None:
            raise self.failure
        self.completed = True
        return self.result


async def test_failed_run_finalizer_appends_error_marker_and_run_complete() -> None:
    """The facade maps all fields and publishes only completed output in order."""
    events = _events()
    repository = _Repository(result=events, failure=None)
    finalizer = FailedRunErrorFinalizer(repository=repository)
    dispatched: list[tuple[str, PublishedEvent]] = []

    async def dispatch_event(session_id: str, event: PublishedEvent) -> None:
        assert repository.completed
        dispatched.append((session_id, event))

    input = _input()
    result = await finalizer.finalize(input, dispatch_event=dispatch_event)
    assert repository.calls == [
        FailedRunFinalization(
            session_id=input.session_id,
            owner_generation=input.owner_generation,
            run_id=input.run_id,
            user_message=input.user_message,
            retry_state=input.retry_state,
            reason=input.reason,
            action_hint=input.action_hint,
        )
    ]
    assert result is not None
    assert result.error_event is events.error_event
    assert result.run_marker is events.run_marker
    assert dispatched[:2] == [
        (input.session_id, events.error_event),
        (input.session_id, events.run_marker),
    ]
    [terminal] = [event for _, event in dispatched if isinstance(event, RunComplete)]
    assert terminal.run_id == input.run_id
    assert dispatched[-1] == (input.session_id, terminal)
    assert len(dispatched) == 3
    payload = result.error_event.payload
    assert isinstance(payload, SystemErrorPayload)
    assert payload.content == "temporary failure"
    assert payload.failure is not None
    assert payload.failure.kind == "failed_run"
    assert payload.failure.finalization_reason == "retry_exhausted"
    assert payload.failure.failed_attempt_count == 10
    marker = result.run_marker.payload
    assert isinstance(marker, RunMarkerPayload)
    assert marker.status == "failed"


async def test_failed_run_finalizer_rejects_stale_owner_before_mutation() -> None:
    """The closed repository's original stale-owner exception propagates."""
    repository = _Repository(
        result=None,
        failure=CanonicalExecutionOwnerGenerationStaleError(
            "Session owner generation is stale",
        ),
    )
    finalizer = FailedRunErrorFinalizer(repository=repository)
    dispatched: list[PublishedEvent] = []

    async def dispatch_event(session_id: str, event: PublishedEvent) -> None:
        del session_id
        dispatched.append(event)

    with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
        await finalizer.finalize(_input(), dispatch_event=dispatch_event)
    assert dispatched == []
    assert not repository.completed
    assert len(repository.calls) == 1


async def test_failed_run_finalizer_yields_to_serialized_stop_intent() -> None:
    """A repository Stop result produces neither publication nor retry."""
    repository = _Repository(result=None, failure=None)
    finalizer = FailedRunErrorFinalizer(repository=repository)
    dispatched: list[PublishedEvent] = []

    async def dispatch_event(session_id: str, event: PublishedEvent) -> None:
        del session_id
        dispatched.append(event)

    result = await finalizer.finalize(_input(), dispatch_event=dispatch_event)
    assert result is None
    assert repository.completed
    assert dispatched == []
    assert len(repository.calls) == 1


async def test_failed_run_repository_cancellation_propagates_without_publication() -> (
    None
):
    repository = _Repository(result=None, failure=asyncio.CancelledError())
    finalizer = FailedRunErrorFinalizer(repository=repository)
    dispatched: list[PublishedEvent] = []

    async def dispatch_event(session_id: str, event: PublishedEvent) -> None:
        del session_id
        dispatched.append(event)

    with pytest.raises(asyncio.CancelledError):
        await finalizer.finalize(_input(), dispatch_event=dispatch_event)
    assert not repository.completed
    assert dispatched == []


@pytest.mark.parametrize("cancelled", [False, True])
async def test_publication_failure_preserves_committed_operation_and_no_retry(
    cancelled: bool,
) -> None:
    events = _events()
    repository = _Repository(result=events, failure=None)
    finalizer = FailedRunErrorFinalizer(repository=repository)
    dispatched: list[PublishedEvent] = []

    async def dispatch_event(session_id: str, event: PublishedEvent) -> None:
        assert repository.completed
        assert session_id == "session-001"
        dispatched.append(event)
        if len(dispatched) == 2:
            if cancelled:
                raise asyncio.CancelledError()
            raise RuntimeError("publication failed")

    expected = asyncio.CancelledError if cancelled else RuntimeError
    with pytest.raises(expected):
        await finalizer.finalize(_input(), dispatch_event=dispatch_event)
    assert repository.completed
    assert len(repository.calls) == 1
    assert dispatched == [events.error_event, events.run_marker]
