"""Live event projector Run-correlation tests."""

import datetime
from typing import cast

import pytest

from azents.broker.broadcast import (
    WebSocketBroadcast,
    WebSocketBroadcastPublishError,
)
from azents.core.enums import AgentRunPhase, AgentRunStatus
from azents.core.inference_profile import AppliedInferenceProfile
from azents.engine.events.engine_events import RunComplete
from azents.engine.events.types import ActiveToolCall
from azents.services.chat.data import ChatLiveRunState
from azents.services.chat.live_events import RedisLiveEventStore
from azents.worker.live.event_projector import LiveEventProjector


class _LiveEventStore:
    """Live event store test double."""

    def __init__(self) -> None:
        self.clear_count = 0

    async def list_by_session_id(self, session_id: str) -> list[object]:
        """Return no partial events."""
        del session_id
        return []

    async def clear_session(self, session_id: str) -> None:
        """Record a session clear."""
        del session_id
        self.clear_count += 1


class _Broadcast:
    """WebSocket broadcast test double."""

    def __init__(self, *, fail: bool = False) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []
        self.fail = fail

    async def publish(self, session_id: str, event: dict[str, object]) -> None:
        """Record a broadcast event or simulate Redis failure."""
        if self.fail:
            raise WebSocketBroadcastPublishError
        self.events.append((session_id, event))


@pytest.mark.asyncio
async def test_stale_terminal_event_does_not_clear_newer_run_projection() -> None:
    """Run A terminal delivery cannot clear the active Run B projection."""
    store = _LiveEventStore()
    broadcast = _Broadcast()
    projector = LiveEventProjector(
        live_event_store=cast(RedisLiveEventStore, store),
        broadcast=cast(WebSocketBroadcast, broadcast),
    )
    await projector.publish_live_run_updated(
        "session-001",
        ChatLiveRunState(
            run_id="run-b",
            phase=AgentRunPhase.WAITING_FOR_MODEL,
            status=AgentRunStatus.RUNNING,
            inference_profile=AppliedInferenceProfile(
                model_target_label="main",
                model_display_name="Test model",
                reasoning_effort=None,
            ),
            retry=None,
        ),
    )

    await projector.update("session-001", RunComplete(run_id="run-a"))
    await projector.publish_live_run_cleared("session-001", run_id="run-a")

    assert store.clear_count == 0
    assert [event[1]["type"] for event in broadcast.events] == ["live_run_updated"]

    await projector.publish_live_run_cleared("session-001", run_id="run-b")

    assert broadcast.events[-1][1] == {
        "type": "live_run_cleared",
        "session_id": "session-001",
        "run_id": "run-b",
    }


@pytest.mark.asyncio
async def test_active_tool_calls_broadcast_without_redis_storage() -> None:
    """Active calls broadcast directly from PostgreSQL state."""
    store = _LiveEventStore()
    broadcast = _Broadcast()
    projector = LiveEventProjector(
        live_event_store=cast(RedisLiveEventStore, store),
        broadcast=cast(WebSocketBroadcast, broadcast),
    )
    active_call = ActiveToolCall(
        call_id="call-1",
        name="bash",
        arguments='{"cmd":"sleep"}',
        started_at=datetime.datetime(2026, 6, 4, tzinfo=datetime.UTC),
        owner_generation=1,
    )

    await projector.replace_active_tool_calls("session-001", [active_call])
    await projector.replace_active_tool_calls("session-001", [])

    assert [event[1]["type"] for event in broadcast.events] == [
        "live_event_upserted",
        "live_event_removed",
    ]
    upserted = broadcast.events[0][1]["event"]
    assert isinstance(upserted, dict)
    payload = upserted["payload"]
    assert isinstance(payload, dict)
    assert payload["call_id"] == "call-1"
    assert broadcast.events[1][1]["event_id"] == upserted["id"]


@pytest.mark.asyncio
async def test_live_run_broadcast_failure_is_non_fatal() -> None:
    """Redis UI publication failure does not escape the projection boundary."""
    projector = LiveEventProjector(
        live_event_store=cast(RedisLiveEventStore, _LiveEventStore()),
        broadcast=cast(WebSocketBroadcast, _Broadcast(fail=True)),
    )

    await projector.publish_live_run_updated(
        "session-001",
        ChatLiveRunState(
            run_id="run-a",
            phase=AgentRunPhase.WAITING_FOR_MODEL,
            status=AgentRunStatus.RUNNING,
            inference_profile=AppliedInferenceProfile(
                model_target_label="main",
                model_display_name="Test model",
                reasoning_effort=None,
            ),
            retry=None,
        ),
    )
    await projector.publish_live_run_cleared("session-001", run_id="run-a")
