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
from azents.engine.events.engine_events import (
    ContentDelta,
    ProviderToolActivityChanged,
    ReasoningDelta,
    RunComplete,
)
from azents.engine.events.types import (
    ActiveToolCall,
    AgentRunState,
    AssistantMessagePayload,
    Event,
    ProviderToolCallPayload,
    ReasoningPayload,
)
from azents.services.chat.data import ChatLiveRunState
from azents.services.chat.live_events import InMemoryLiveEventStore, RedisLiveEventStore
from azents.testing.types import is_string_object_dict
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


class _AgentSessionRepository:
    """Expose the durable owner generation used for projection admission."""

    def __init__(self, owner_generation: int = 1) -> None:
        self.owner_generation = owner_generation

    async def get_by_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> object:
        del session, session_id
        return type(
            "_Session",
            (),
            {"owner_generation": self.owner_generation},
        )()


class _LiveEventStore(InMemoryLiveEventStore):
    """Live event store test double."""

    def __init__(self) -> None:
        super().__init__()
        self.clear_count = 0

    async def _clear_for_owner(
        self,
        session_id: str,
        owner_generation: int,
    ) -> bool:
        """Record a session clear."""
        cleared = await super()._clear_for_owner(session_id, owner_generation)
        if not cleared:
            return False
        self.clear_count += 1
        return True


class _FailingDiscardStore(_LiveEventStore):
    """Fail model-partial lookup during best-effort discard."""

    async def _list_for_owner(
        self,
        session_id: str,
        owner_generation: int,
    ) -> list[Event]:
        """Simulate a live-store read failure."""
        del session_id, owner_generation
        raise RuntimeError("live store unavailable")


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

    async def publish_live_projection(
        self,
        session_id: str,
        event: dict[str, object],
        *,
        owner_generation: int,
    ) -> bool:
        """Record a generation-gated projection event."""
        del owner_generation
        await self.publish(session_id, event)
        return True


def _running_run(run_id: str) -> AgentRunState:
    """Create one durable running Run projection."""
    now = datetime.datetime.now(datetime.UTC)
    return AgentRunState(
        id=run_id,
        session_id="session-001",
        scheduled_task_cycle_id=None,
        run_index=1,
        phase=AgentRunPhase.WAITING_FOR_MODEL,
        status=AgentRunStatus.RUNNING,
        parent_agent_run_id=None,
        requested_model_target_label=None,
        requested_reasoning_effort=None,
        requested_enabled_execution_options=[],
        active_tool_calls=[],
        last_completed_event_id=None,
        parent_result_delivery_state=None,
        parent_result_mailbox_item_id=None,
        parent_result_enqueued_at=None,
        stop_requested_at=None,
        created_at=now,
        started_at=now,
        model_call_started_at=now,
        ended_at=None,
        updated_at=now,
    )


def _projector(
    store: object,
    broadcast: _Broadcast,
    *,
    current_run: AgentRunState | None = None,
    owner_generation: int = 1,
    session_repository: _AgentSessionRepository | None = None,
) -> LiveEventProjector:
    """Create a projector with durable correlation doubles."""
    return LiveEventProjector(
        live_event_store=cast(RedisLiveEventStore, store),
        broadcast=cast(WebSocketBroadcast, broadcast),
        session_manager=_SessionManager(),
        agent_run_repository=cast(Any, _AgentRunRepository(current_run)),
        agent_session_repository=cast(
            Any,
            session_repository or _AgentSessionRepository(owner_generation),
        ),
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
                enabled_execution_options=[],
            ),
            model_call_started_at=datetime.datetime(2026, 7, 14, tzinfo=datetime.UTC),
            retry=None,
        ),
        owner_generation=1,
    )

    await projector.update(
        "session-001", RunComplete(run_id="run-a"), owner_generation=1
    )
    await projector.publish_live_run_cleared(
        "session-001", run_id="run-a", owner_generation=1
    )

    assert store.clear_count == 0
    assert [event[1]["type"] for event in broadcast.events] == ["live_run_updated"]
    live_run = broadcast.events[0][1]["run"]
    assert is_string_object_dict(live_run)
    assert live_run["model_call_started_at"] == "2026-07-14T00:00:00+00:00"

    await projector.publish_live_run_cleared(
        "session-001", run_id="run-b", owner_generation=1
    )

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
        owner_generation=1,
    )
    await projector.publish_live_run_cleared(
        "session-001",
        run_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        owner_generation=1,
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
        wire_dialect="json_function",
    )

    await projector.replace_active_tool_calls(
        "session-001",
        [active_call],
        removed_call_ids=set(),
        owner_generation=1,
    )
    restarted_projector = _projector(store, broadcast)
    await restarted_projector.replace_active_tool_calls(
        "session-001",
        [],
        removed_call_ids={"call-1"},
        owner_generation=1,
    )

    assert [event[1]["type"] for event in broadcast.events] == [
        "live_event_upserted",
        "live_event_removed",
    ]
    upserted = broadcast.events[0][1]["event"]
    assert is_string_object_dict(upserted)
    payload = upserted["payload"]
    assert is_string_object_dict(payload)
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
                enabled_execution_options=[],
            ),
            model_call_started_at=datetime.datetime(2026, 7, 14, tzinfo=datetime.UTC),
            retry=None,
        ),
        owner_generation=1,
    )
    await projector.publish_live_run_cleared(
        "session-001", run_id="run-a", owner_generation=1
    )


@pytest.mark.asyncio
async def test_provider_tool_activity_upserts_and_discards_with_model_attempt() -> None:
    """Provider-tool snapshots share stable identity and retry cleanup."""
    store = InMemoryLiveEventStore()
    broadcast = _Broadcast()
    projector = _projector(store, broadcast)

    await projector.update(
        "session-001",
        ProviderToolActivityChanged(
            call_id="search-1",
            name="web_search",
            status="running",
            arguments=None,
        ),
        owner_generation=1,
    )
    running_events = await store.list_by_session_id("session-001")
    assert len(running_events) == 1
    running = running_events[0]
    assert isinstance(running.payload, ProviderToolCallPayload)
    assert running.payload.status == "running"

    await projector.update(
        "session-001",
        ProviderToolActivityChanged(
            call_id="search-1",
            name="web_search",
            status="completed",
            arguments='{"query":"azents"}',
        ),
        owner_generation=1,
    )
    completed_events = await store.list_by_session_id("session-001")
    assert len(completed_events) == 1
    completed = completed_events[0]
    assert completed.id == running.id
    assert completed.created_at == running.created_at
    assert isinstance(completed.payload, ProviderToolCallPayload)
    assert completed.payload.status == "completed"
    assert completed.payload.arguments == '{"query":"azents"}'

    await projector.discard_failed_attempt("session-001", owner_generation=1)

    assert await store.list_by_session_id("session-001") == []
    assert [event[1]["type"] for event in broadcast.events] == [
        "live_event_upserted",
        "live_event_upserted",
        "live_event_removed",
    ]


@pytest.mark.asyncio
async def test_reasoning_stream_preserves_item_and_summary_boundaries() -> None:
    """Project each reasoning item separately and delimit its summary parts."""
    store = InMemoryLiveEventStore()
    broadcast = _Broadcast()
    projector = _projector(store, broadcast)

    for event in (
        ReasoningDelta(
            delta="first",
            item_id="rs_1",
            output_index=0,
            summary_index=0,
        ),
        ReasoningDelta(
            delta="second",
            item_id="rs_1",
            output_index=0,
            summary_index=1,
        ),
        ReasoningDelta(
            delta="third",
            item_id="rs_2",
            output_index=1,
            summary_index=0,
        ),
    ):
        await projector.update("session-001", event, owner_generation=1)
    await projector.flush_session("session-001", owner_generation=1)

    reasoning_events = await store.list_by_session_id("session-001")
    assert len(reasoning_events) == 2
    assert [
        event.payload.text
        for event in reasoning_events
        if isinstance(event.payload, ReasoningPayload)
    ] == ["first\nsecond", "third"]
    assert [event[1]["type"] for event in broadcast.events] == [
        "live_event_upserted",
        "live_event_upserted",
        "live_event_upserted",
    ]


@pytest.mark.asyncio
async def test_reasoning_identity_promotion_broadcasts_previous_id_removal() -> None:
    """Remove the output-position block before upserting its item-ID successor."""
    store = InMemoryLiveEventStore()
    broadcast = _Broadcast()
    projector = _projector(store, broadcast)

    await projector.update(
        "session-001",
        ReasoningDelta(
            delta="first",
            item_id=None,
            output_index=0,
            summary_index=0,
        ),
        owner_generation=1,
    )
    await projector.update(
        "session-001",
        ReasoningDelta(
            delta=" continued",
            item_id="rs_1",
            output_index=0,
            summary_index=0,
        ),
        owner_generation=1,
    )
    await projector.flush_session("session-001", owner_generation=1)

    reasoning_events = await store.list_by_session_id("session-001")
    assert len(reasoning_events) == 1
    assert isinstance(reasoning_events[0].payload, ReasoningPayload)
    assert reasoning_events[0].payload.text == "first continued"
    assert [event[1]["type"] for event in broadcast.events] == [
        "live_event_upserted",
        "live_event_removed",
        "live_event_upserted",
    ]


@pytest.mark.asyncio
async def test_failed_attempt_discard_store_failure_is_non_fatal() -> None:
    """Live-store cleanup failure does not block durable retry handling."""
    projector = _projector(_FailingDiscardStore(), _Broadcast())

    await projector.discard_failed_attempt("session-001", owner_generation=1)


@pytest.mark.asyncio
async def test_failed_attempt_discards_published_model_partials() -> None:
    """Failed-attempt cleanup removes assistant and reasoning live state."""
    store = InMemoryLiveEventStore()
    broadcast = _Broadcast()
    projector = _projector(store, broadcast)

    await projector.update(
        "session-001",
        ContentDelta(delta="failed prefix", content_index=0),
        owner_generation=1,
    )
    await projector.update(
        "session-001",
        ReasoningDelta(
            delta="failed reasoning",
            item_id="rs_failed",
            output_index=1,
            summary_index=0,
        ),
        owner_generation=1,
    )
    await projector.flush_session("session-001", owner_generation=1)

    assert len(await store.list_by_session_id("session-001")) == 2

    await projector.discard_failed_attempt("session-001", owner_generation=1)

    assert await store.list_by_session_id("session-001") == []
    assert [event[1]["type"] for event in broadcast.events] == [
        "live_event_upserted",
        "live_event_upserted",
        "live_event_removed",
        "live_event_removed",
    ]


@pytest.mark.asyncio
async def test_takeover_rejects_old_buffer_flush_and_clear() -> None:
    """A new durable generation makes buffered old live cleanup a no-op."""
    store = InMemoryLiveEventStore()
    broadcast = _Broadcast()
    sessions = _AgentSessionRepository(owner_generation=1)
    projector = _projector(
        store,
        broadcast,
        session_repository=sessions,
    )

    await projector.update(
        "session-001",
        ContentDelta(delta="stale partial", content_index=0),
        owner_generation=1,
    )
    sessions.owner_generation = 2
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
                enabled_execution_options=[],
            ),
            model_call_started_at=None,
            retry=None,
        ),
        owner_generation=2,
    )
    await projector.update(
        "session-001",
        ContentDelta(delta="fresh partial", content_index=0),
        owner_generation=2,
    )
    await projector.flush_session("session-001", owner_generation=2)

    await projector.flush_session("session-001", owner_generation=1)
    await projector.clear_session("session-001", owner_generation=1)

    events = await store.list_by_session_id("session-001")
    assert len(events) == 1
    assert isinstance(events[0].payload, AssistantMessagePayload)
    assert events[0].payload.content == "fresh partial"
    assert [event[1]["type"] for event in broadcast.events] == [
        "live_run_updated",
        "live_event_upserted",
    ]


@pytest.mark.asyncio
async def test_control_event_reseeds_empty_store_and_rejects_stale_owner() -> None:
    """Current controls seed an empty fence while stale controls stay private."""
    store = InMemoryLiveEventStore()
    broadcast = _Broadcast()
    sessions = _AgentSessionRepository(owner_generation=2)
    projector = _projector(
        store,
        broadcast,
        session_repository=sessions,
    )
    event: dict[str, object] = {
        "type": "todo_state_changed",
        "todo": {"items": []},
    }

    await projector.publish_control_event(
        "session-001",
        event,
        owner_generation=2,
    )
    await projector.publish_control_event(
        "session-001",
        {"type": "runtime_error", "message": "stale"},
        owner_generation=1,
    )

    assert broadcast.events == [("session-001", event)]
    current_store = store.for_owner("session-001", 2)
    await current_store.append_assistant_delta(
        "session-001",
        delta="current",
        content_index=0,
    )
    assert len(await store.list_by_session_id("session-001")) == 1
