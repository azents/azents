"""Live event projector Run-correlation tests."""

import datetime
from contextlib import AbstractAsyncContextManager
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.broadcast import (
    WebSocketBroadcast,
    WebSocketBroadcastPublishError,
)
from azents.core.enums import AgentRunPhase, AgentRunStatus
from azents.core.inference_profile import AppliedInferenceProfile
from azents.engine.events.engine_events import RunComplete
from azents.engine.events.types import ActiveToolCall, AgentRunState
from azents.services.chat.data import ChatLiveRunState
from azents.services.chat.live_events import RedisLiveEventStore
from azents.worker.live.event_projector import LiveEventProjector


class _SessionScope(AbstractAsyncContextManager[AsyncSession]):
    """Return a minimal AsyncSession placeholder."""

    async def __aenter__(self) -> AsyncSession:
        """Enter the placeholder session scope."""
        return cast(AsyncSession, object())

    async def __aexit__(self, *exc_info: object) -> None:
        """Exit the placeholder session scope."""


class _SessionManager:
    """Create placeholder session scopes."""

    def __call__(self) -> _SessionScope:
        """Return one placeholder scope."""
        return _SessionScope()


class _AgentRunRepository:
    """Expose the durable current Run used for terminal correlation."""

    def __init__(self, current: AgentRunState | None = None) -> None:
        self.current = current

    async def get_running_by_session_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> AgentRunState | None:
        """Return the configured durable current Run."""
        del session, session_id
        return self.current


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


def _running_run(run_id: str) -> AgentRunState:
    """Create one durable running Run projection."""
    now = datetime.datetime.now(datetime.UTC)
    return AgentRunState(
        id=run_id,
        session_id="session-001",
        run_index=1,
        phase=AgentRunPhase.WAITING_FOR_MODEL,
        status=AgentRunStatus.RUNNING,
        parent_agent_run_id=None,
        active_tool_calls=[],
        last_completed_event_id=None,
        stop_requested_at=None,
        created_at=now,
        started_at=now,
        ended_at=None,
        updated_at=now,
    )


def _projector(
    store: _LiveEventStore,
    broadcast: _Broadcast,
    *,
    current_run: AgentRunState | None = None,
) -> LiveEventProjector:
    """Create a projector with durable correlation doubles."""
    return LiveEventProjector(
        live_event_store=cast(RedisLiveEventStore, store),
        broadcast=cast(WebSocketBroadcast, broadcast),
        session_manager=_SessionManager(),
        agent_run_repository=cast(Any, _AgentRunRepository(current_run)),
    )


@pytest.mark.asyncio
async def test_stale_terminal_event_does_not_clear_newer_run_projection() -> None:
    """Run A terminal delivery cannot clear the active Run B projection."""
    store = _LiveEventStore()
    broadcast = _Broadcast()
    projector = _projector(store, broadcast)
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
async def test_stale_terminal_after_restart_uses_durable_current_run() -> None:
    """A fresh projector rejects Run A terminal cleanup while Run B is active."""
    store = _LiveEventStore()
    broadcast = _Broadcast()
    projector = _projector(
        store,
        broadcast,
        current_run=_running_run("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"),
    )

    await projector.update(
        "session-001",
        RunComplete(run_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
    )
    await projector.publish_live_run_cleared(
        "session-001",
        run_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    )

    assert store.clear_count == 0
    assert broadcast.events == []


@pytest.mark.asyncio
async def test_active_tool_calls_broadcast_without_redis_storage() -> None:
    """Active calls broadcast directly from PostgreSQL state."""
    store = _LiveEventStore()
    broadcast = _Broadcast()
    projector = _projector(store, broadcast)
    active_call = ActiveToolCall(
        call_id="call-1",
        name="bash",
        arguments='{"cmd":"sleep"}',
        started_at=datetime.datetime(2026, 6, 4, tzinfo=datetime.UTC),
        owner_generation=1,
    )

    await projector.replace_active_tool_calls(
        "session-001",
        [active_call],
        removed_call_ids=set(),
    )
    restarted_projector = _projector(store, broadcast)
    await restarted_projector.replace_active_tool_calls(
        "session-001",
        [],
        removed_call_ids={"call-1"},
    )

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
    projector = _projector(_LiveEventStore(), _Broadcast(fail=True))

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
