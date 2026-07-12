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


class _Engine:
    """Engine test double that stores one user-safe error event."""

    async def save_error_message(self, session_id: str, content: str) -> Event:
        """Return a durable system error event."""
        return make_system_error_event(session_id=session_id, content=content)


class _Publisher:
    """Worker event publisher test double."""

    def __init__(self) -> None:
        self.events: list[tuple[str, PublishedEvent]] = []

    async def dispatch_event(self, session_id: str, event: PublishedEvent) -> None:
        """Record a published event."""
        self.events.append((session_id, event))


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
        await reporter.report_unhandled("session-001", exc)

    assert len(publisher.events) == 1
    assert isinstance(publisher.events[0][1], Event)
    assert not any(isinstance(event, RunComplete) for _, event in publisher.events)
