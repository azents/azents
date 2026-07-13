"""Worker event publisher projection-boundary tests."""

from typing import Any, cast

import pytest

from azents.broker.broadcast import WebSocketBroadcast
from azents.broker.serialization import serialize_event
from azents.broker.types import SessionBroker
from azents.engine.events.builders import make_system_error_event
from azents.engine.events.engine_events import (
    AccountLinkNudgeEvent,
    AuthorizationRequestEvent,
    CompactionComplete,
    CompactionStarted,
    RunStarted,
    RuntimeErrorEvent,
    SubagentTreeChanged,
    TodoStateChanged,
)
from azents.worker.events.publisher import PublicChatControlEvent, WorkerEventPublisher
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

    async def flush_session(self, session_id: str) -> None:
        """Accept durable handoff flush."""
        del session_id

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
    event = make_system_error_event(session_id="session-1", content="failed")

    await publisher.dispatch_event("session-1", event)

    assert projector.events == [("session-1", event)]


class _TrackingBroadcast:
    """Record canonical broadcast order."""

    def __init__(self, calls: list[object]) -> None:
        self.calls = calls

    async def publish(self, session_id: str, event: dict[str, object]) -> None:
        """Record one published frame."""
        self.calls.append(("publish", session_id, event))


class _TrackingBroker:
    """Record TTL renewal order."""

    def __init__(self, calls: list[object]) -> None:
        self.calls = calls

    async def renew_session_ttl(self, session_id: str) -> None:
        """Record TTL renewal."""
        self.calls.append(("ttl", session_id))


class _TrackingProjector:
    """Record durable handoff projection order."""

    def __init__(self, calls: list[object]) -> None:
        self.calls = calls

    async def flush_session(self, session_id: str) -> None:
        """Record pre-handoff partial flush."""
        self.calls.append(("flush", session_id))

    async def update(self, session_id: str, event: object) -> None:
        """Record post-history counterpart removal."""
        self.calls.append(("update", session_id, event))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event",
    [
        RuntimeErrorEvent(message="runtime failed"),
        AuthorizationRequestEvent(toolkit_id="toolkit-1", toolkit_name="GitHub"),
        AccountLinkNudgeEvent(
            toolkit_name="GitHub",
            toolkit_type="github",
            toolkit_id="toolkit-1",
        ),
        CompactionStarted(),
        CompactionComplete(),
        TodoStateChanged(todo={"items": []}),
        SubagentTreeChanged(
            root_session_agent_id="root-1",
            changed_session_agent_id="child-1",
        ),
    ],
)
async def test_public_control_event_retains_direct_wire_delivery(
    event: PublicChatControlEvent,
) -> None:
    """Canonical public controls retain direct WebSocket delivery."""
    calls: list[object] = []
    publisher = WorkerEventPublisher(
        broker=cast(SessionBroker, cast(Any, _TrackingBroker(calls))),
        broadcast=cast(WebSocketBroadcast, _TrackingBroadcast(calls)),
        live_event_projector=cast(LiveEventProjector, _TrackingProjector(calls)),
    )

    await publisher.dispatch_event("session-1", event)

    assert calls == [
        ("publish", "session-1", serialize_event(event)),
        ("ttl", "session-1"),
        ("update", "session-1", event),
    ]


@pytest.mark.asyncio
async def test_internal_runtime_event_is_not_publicly_broadcast() -> None:
    """Internal runtime telemetry feeds projection without becoming public frames."""
    calls: list[object] = []
    publisher = WorkerEventPublisher(
        broker=cast(SessionBroker, cast(Any, _TrackingBroker(calls))),
        broadcast=cast(WebSocketBroadcast, _TrackingBroadcast(calls)),
        live_event_projector=cast(LiveEventProjector, _TrackingProjector(calls)),
    )
    event = RunStarted(run_id="run-1", phase=None)

    await publisher.dispatch_event("session-1", event)

    assert not any(isinstance(call, tuple) and call[0] == "publish" for call in calls)
    assert calls == [
        ("ttl", "session-1"),
        ("update", "session-1", event),
    ]


@pytest.mark.asyncio
async def test_durable_event_uses_one_canonical_history_frame_after_flush() -> None:
    """Durable handoff flushes live partials before the canonical history action."""
    calls: list[object] = []
    publisher = WorkerEventPublisher(
        broker=cast(SessionBroker, cast(Any, _TrackingBroker(calls))),
        broadcast=cast(WebSocketBroadcast, _TrackingBroadcast(calls)),
        live_event_projector=cast(LiveEventProjector, _TrackingProjector(calls)),
    )
    event = make_system_error_event(session_id="session-1", content="failed")

    await publisher.dispatch_event("session-1", event)

    assert calls[0] == ("flush", "session-1")
    published = [
        call for call in calls if isinstance(call, tuple) and call[0] == "publish"
    ]
    assert len(published) == 1
    assert published[0][2]["type"] == "history_event_appended"
    assert calls[-1] == ("update", "session-1", event)
