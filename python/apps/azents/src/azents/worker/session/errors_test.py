"""Session runner error reporting tests."""

from typing import cast

import pytest

from azents.broker.types import PublishedEvent
from azents.engine.events.builders import make_system_error_event
from azents.engine.events.engine_events import RunComplete
from azents.engine.events.types import Event
from azents.engine.run.contracts import AgentEngineProtocol
from azents.worker.events.publisher import WorkerEventPublisher
from azents.worker.session.errors import SessionRunnerErrorReporter
from azents.worker.session.execution_snapshot import (
    CanonicalExecutionOwnerGenerationStaleError,
)


class _Engine:
    """Engine test double that stores one user-safe error event."""

    async def save_error_message(
        self,
        session_id: str,
        content: str,
        *,
        owner_generation: int,
    ) -> Event:
        """Return a durable system error event."""
        del owner_generation
        return make_system_error_event(session_id=session_id, content=content)


class _Publisher:
    """Worker event publisher test double."""

    def __init__(self) -> None:
        self.events: list[tuple[str, PublishedEvent]] = []

    async def dispatch_event(
        self,
        session_id: str,
        event: PublishedEvent,
        *,
        owner_generation: int,
    ) -> None:
        """Record a published event."""
        del owner_generation
        self.events.append((session_id, event))


class _StaleEngine(_Engine):
    """Engine test double that rejects an obsolete owner generation."""

    async def save_error_message(
        self,
        session_id: str,
        content: str,
        *,
        owner_generation: int,
    ) -> Event:
        """Reject stale error-event persistence."""
        del session_id, content, owner_generation
        raise CanonicalExecutionOwnerGenerationStaleError("owner is stale")


class _FailingEngine(_Engine):
    """Engine test double that cannot durably save an error event."""

    async def save_error_message(
        self,
        session_id: str,
        content: str,
        *,
        owner_generation: int,
    ) -> Event:
        """Expose the persistence failure without inventing transient history."""
        del session_id, content, owner_generation
        raise RuntimeError("database unavailable")


@pytest.mark.asyncio
async def test_report_unhandled_does_not_invent_terminal_run_event() -> None:
    """A pre-Run error remains an observation without RunComplete."""
    publisher = _Publisher()
    reporter = SessionRunnerErrorReporter(
        engine=cast(AgentEngineProtocol, _Engine()),
        event_publisher=cast(WorkerEventPublisher, publisher),
    )

    try:
        raise RuntimeError("pre-run failure")
    except RuntimeError as exc:
        await reporter.report_unhandled(
            "session-001",
            exc,
            owner_generation=1,
        )

    assert len(publisher.events) == 1
    assert isinstance(publisher.events[0][1], Event)
    assert not any(isinstance(event, RunComplete) for _, event in publisher.events)


@pytest.mark.asyncio
async def test_report_unhandled_does_not_publish_fallback_for_stale_owner() -> None:
    """Owner rejection does not publish an unfenced synthetic error event."""
    publisher = _Publisher()
    reporter = SessionRunnerErrorReporter(
        engine=cast(AgentEngineProtocol, _StaleEngine()),
        event_publisher=cast(WorkerEventPublisher, publisher),
    )

    with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
        await reporter.report_unhandled(
            "session-001",
            RuntimeError("pre-run failure"),
            owner_generation=1,
        )

    assert publisher.events == []


@pytest.mark.asyncio
async def test_report_unhandled_does_not_publish_phantom_history_on_save_failure() -> (
    None
):
    """A failed durable append cannot become a synthetic history broadcast."""
    publisher = _Publisher()
    reporter = SessionRunnerErrorReporter(
        engine=cast(AgentEngineProtocol, _FailingEngine()),
        event_publisher=cast(WorkerEventPublisher, publisher),
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        await reporter.report_unhandled(
            "session-001",
            RuntimeError("pre-run failure"),
            owner_generation=1,
        )

    assert publisher.events == []
