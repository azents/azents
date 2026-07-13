"""Worker event publisher projection-boundary tests."""

from typing import Any, cast

import pytest

from azents.broker.broadcast import WebSocketBroadcast
from azents.broker.types import SessionBroker
from azents.engine.events.engine_events import RunStarted
from azents.worker.events.publisher import WorkerEventPublisher
from azents.worker.live.event_projector import LiveEventProjector


class _FailingBroadcast:
    """Broadcast test double that rejects publication."""

    async def publish(self, session_id: str, event: dict[str, object]) -> None:
        """Simulate an unavailable projection transport."""
        del session_id, event
        raise RuntimeError("broadcast unavailable")


class _FailingTtlBroker:
    """Broker test double that rejects TTL renewal."""

    async def renew_session_ttl(self, session_id: str) -> None:
        """Simulate unavailable ephemeral session metadata."""
        del session_id
        raise RuntimeError("TTL unavailable")


class _Projector:
    """Live projector test double."""

    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    async def update(self, session_id: str, event: object) -> None:
        """Record projection attempts."""
        self.events.append((session_id, event))


@pytest.mark.asyncio
async def test_projection_transport_failures_do_not_interrupt_dispatch() -> None:
    """WebSocket and TTL failures do not terminalize a valid runtime event."""
    projector = _Projector()
    publisher = WorkerEventPublisher(
        broker=cast(SessionBroker, cast(Any, _FailingTtlBroker())),
        broadcast=cast(WebSocketBroadcast, _FailingBroadcast()),
        live_event_projector=cast(LiveEventProjector, projector),
    )
    event = RunStarted(run_id="run-1", phase=None)

    await publisher.dispatch_event("session-1", event)

    assert projector.events == [("session-1", event)]
