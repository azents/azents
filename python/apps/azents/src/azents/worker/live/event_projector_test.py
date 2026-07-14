"""Live event projector Run-correlation tests."""

import asyncio
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
    ReasoningDelta,
    RunComplete,
    RunStarted,
)
from azents.engine.events.types import (
    ActiveToolCall,
    AgentRunState,
    AssistantMessagePayload,
    Event,
)
from azents.services.chat import live_events as live_events_module
from azents.services.chat.data import ChatLiveRunState
from azents.services.chat.live_events import InMemoryLiveEventStore, RedisLiveEventStore
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

    async def list_latest_by_session_ids(
        self,
        session: AsyncSession,
        *,
        session_ids: list[str],
    ) -> dict[str, AgentRunState]:
        """Return the configured durable current Run."""
        del session
        if self.current is None or self.current.session_id not in session_ids:
            return {}
        return {self.current.session_id: self.current}

    async def get_active_by_session_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> AgentRunState | None:
        """Return the configured Run only while it remains active."""
        del session
        if (
            self.current is None
            or self.current.session_id != session_id
            or self.current.status
            not in {AgentRunStatus.PENDING, AgentRunStatus.RUNNING}
        ):
            return None
        return self.current


class _BlockingAgentRunRepository(_AgentRunRepository):
    """Pause one durable lookup to expose an update/clear interleaving."""

    def __init__(self, current: AgentRunState | None = None) -> None:
        super().__init__(current)
        self.lookup_started = asyncio.Event()
        self.release_lookup = asyncio.Event()

    async def list_latest_by_session_ids(
        self,
        session: AsyncSession,
        *,
        session_ids: list[str],
    ) -> dict[str, AgentRunState]:
        """Block the first durable lookup until the test releases it."""
        del session
        self.lookup_started.set()
        await self.release_lookup.wait()
        if self.current is None or self.current.session_id not in session_ids:
            return {}
        return {self.current.session_id: self.current}


class _BlockingFirstActiveLookupRepository(_AgentRunRepository):
    """Return a captured first active Run after a newer Run is projected."""

    def __init__(self, current: AgentRunState) -> None:
        super().__init__(current)
        self.lookup_started = asyncio.Event()
        self.release_lookup = asyncio.Event()
        self._active_lookup_count = 0

    async def get_active_by_session_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> AgentRunState | None:
        """Block only the first lookup and preserve its pre-race result."""
        self._active_lookup_count += 1
        captured = self.current
        if self._active_lookup_count == 1:
            self.lookup_started.set()
            await self.release_lookup.wait()
            return captured
        return await super().get_active_by_session_id(
            session,
            session_id=session_id,
        )


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


class _HangingRedis:
    """Redis double that never answers the Run-start projection read."""

    async def hvals(self, key: str) -> list[bytes]:
        """Block until RedisLiveEventStore applies its operation deadline."""
        del key
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class _AmbiguousFirstPartialStore(InMemoryLiveEventStore):
    """Fail the first partial with a commit-ambiguous Redis timeout."""

    def __init__(self) -> None:
        super().__init__()
        self.attempted_content_indexes: list[int] = []

    async def append_assistant_delta(
        self,
        session_id: str,
        *,
        delta: str,
        content_index: int,
        now: datetime.datetime | None = None,
    ) -> Event:
        """Raise one timeout, then project subsequent batches normally."""
        self.attempted_content_indexes.append(content_index)
        if len(self.attempted_content_indexes) == 1:
            raise TimeoutError
        return await super().append_assistant_delta(
            session_id,
            delta=delta,
            content_index=content_index,
            now=now,
        )


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


class _GatedClearBroadcast(_Broadcast):
    """Hold clear publication so concurrent duplicate attempts overlap."""

    def __init__(self) -> None:
        super().__init__()
        self.clear_publish_started = asyncio.Event()
        self.release_clear_publish = asyncio.Event()
        self.clear_publish_attempts = 0

    async def publish(self, session_id: str, event: dict[str, object]) -> None:
        """Pause each clear attempt until explicitly released."""
        if event.get("type") == "live_run_cleared":
            self.clear_publish_attempts += 1
            self.clear_publish_started.set()
            await self.release_clear_publish.wait()
        await super().publish(session_id, event)


class _GatedPartialBroadcast(_Broadcast):
    """Hold one partial upsert after its live projection was committed."""

    def __init__(self) -> None:
        super().__init__()
        self.partial_publish_started = asyncio.Event()
        self.block_partial = True

    async def publish(self, session_id: str, event: dict[str, object]) -> None:
        """Pause the first live partial upsert until cancellation."""
        if self.block_partial and event.get("type") == "live_event_upserted":
            self.partial_publish_started.set()
            await asyncio.Event().wait()
        await super().publish(session_id, event)


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
        model_call_started_at=now,
        ended_at=None,
        updated_at=now,
    )


def _projector(
    store: object,
    broadcast: _Broadcast,
    *,
    current_run: AgentRunState | None = None,
    agent_run_repository: _AgentRunRepository | None = None,
) -> LiveEventProjector:
    """Create a projector with durable correlation doubles."""
    return LiveEventProjector(
        live_event_store=cast(RedisLiveEventStore, store),
        broadcast=cast(WebSocketBroadcast, broadcast),
        session_manager=_SessionManager(),
        agent_run_repository=cast(
            Any,
            agent_run_repository or _AgentRunRepository(current_run),
        ),
    )


@pytest.mark.asyncio
async def test_run_started_returns_after_hung_redis_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run startup can proceed when non-durable Redis projection is hung."""
    monkeypatch.setattr(
        live_events_module,
        "_LIVE_EVENT_REDIS_OPERATION_TIMEOUT_SECONDS",
        0.01,
    )
    run_id = "a" * 32
    projector = _projector(
        RedisLiveEventStore(_HangingRedis()),
        _Broadcast(),
        current_run=_running_run(run_id),
    )

    await asyncio.wait_for(
        projector.update(
            "session-001",
            RunStarted(run_id=run_id, phase=AgentRunPhase.WAITING_FOR_MODEL),
        ),
        timeout=0.2,
    )


@pytest.mark.asyncio
async def test_partial_broadcast_failure_does_not_replay_committed_delta() -> None:
    """A failed best-effort broadcast cannot duplicate Redis live text."""
    store = InMemoryLiveEventStore()
    run_id = "a" * 32
    repository = _AgentRunRepository(_running_run(run_id))
    projector = _projector(
        store,
        _Broadcast(fail=True),
        agent_run_repository=repository,
    )
    await projector.update(
        "session-001",
        RunStarted(run_id=run_id, phase=AgentRunPhase.WAITING_FOR_MODEL),
    )

    await projector.update(
        "session-001",
        ContentDelta(run_id=run_id, delta="hello", content_index=0),
    )
    await projector.flush_session("session-001")
    await projector.flush_session("session-001")

    events = await store.list_by_session_id("session-001")
    assert len(events) == 1
    payload = events[0].payload
    assert isinstance(payload, AssistantMessagePayload)
    assert payload.content == "hello"


@pytest.mark.asyncio
async def test_cancelled_partial_broadcast_retries_only_uncommitted_batches() -> None:
    """Cancellation after store append preserves only later partial batches."""
    store = InMemoryLiveEventStore()
    broadcast = _GatedPartialBroadcast()
    run_id = "a" * 32
    repository = _AgentRunRepository(_running_run(run_id))
    projector = _projector(
        store,
        broadcast,
        agent_run_repository=repository,
    )
    await projector.update(
        "session-001",
        RunStarted(run_id=run_id, phase=AgentRunPhase.WAITING_FOR_MODEL),
    )
    await projector.update(
        "session-001",
        ContentDelta(run_id=run_id, delta="first", content_index=0),
    )
    await projector.update(
        "session-001",
        ContentDelta(run_id=run_id, delta="second", content_index=1),
    )

    flush = asyncio.create_task(projector.flush_session("session-001"))
    await broadcast.partial_publish_started.wait()
    flush.cancel()
    with pytest.raises(asyncio.CancelledError):
        await flush

    broadcast.block_partial = False
    await projector.flush_session("session-001")
    contents = []
    for event in await store.list_by_session_id("session-001"):
        payload = event.payload
        assert isinstance(payload, AssistantMessagePayload)
        contents.append(payload.content)
    assert contents == ["first", "second"]


@pytest.mark.asyncio
async def test_ambiguous_partial_store_failure_drops_only_current_batch() -> None:
    """Redis response loss cannot replay text whose commit is unknown."""
    store = _AmbiguousFirstPartialStore()
    run_id = "a" * 32
    projector = _projector(
        store,
        _Broadcast(),
        current_run=_running_run(run_id),
    )
    await projector.update(
        "session-001",
        RunStarted(run_id=run_id, phase=AgentRunPhase.WAITING_FOR_MODEL),
    )
    await projector.update(
        "session-001",
        ContentDelta(run_id=run_id, delta="ambiguous", content_index=0),
    )
    await projector.update(
        "session-001",
        ContentDelta(run_id=run_id, delta="pending", content_index=1),
    )

    await projector.flush_session("session-001")
    await projector.flush_session("session-001")

    assert store.attempted_content_indexes == [0, 1]
    events = await store.list_by_session_id("session-001")
    assert len(events) == 1
    payload = events[0].payload
    assert isinstance(payload, AssistantMessagePayload)
    assert payload.content == "pending"


@pytest.mark.asyncio
async def test_new_run_discards_stale_pending_partial_batches() -> None:
    """Run B start drops buffered and late Run A partials before projection."""
    store = InMemoryLiveEventStore()
    broadcast = _Broadcast()
    run_a = "a" * 32
    run_b = "b" * 32
    repository = _AgentRunRepository(_running_run(run_a))
    projector = _projector(
        store,
        broadcast,
        agent_run_repository=repository,
    )
    await projector.update(
        "session-001",
        RunStarted(run_id=run_a, phase=AgentRunPhase.WAITING_FOR_MODEL),
    )
    await projector.update(
        "session-001",
        ContentDelta(run_id=run_a, delta="stale", content_index=0),
    )

    repository.current = _running_run(run_b)
    await projector.update(
        "session-001",
        RunStarted(run_id=run_b, phase=AgentRunPhase.WAITING_FOR_MODEL),
    )
    await projector.update(
        "session-001",
        ContentDelta(run_id=run_a, delta="late", content_index=0),
    )
    await projector.update(
        "session-001",
        ContentDelta(run_id=run_b, delta="current", content_index=0),
    )
    await projector.flush_session("session-001")

    events = await store.list_by_session_id("session-001")
    assert len(events) == 1
    payload = events[0].payload
    assert isinstance(payload, AssistantMessagePayload)
    assert payload.content == "current"


@pytest.mark.asyncio
async def test_partial_flush_revalidates_durable_active_run() -> None:
    """A buffered Run A partial is dropped once PostgreSQL activates Run B."""
    store = InMemoryLiveEventStore()
    run_a = "a" * 32
    run_b = "b" * 32
    repository = _AgentRunRepository(_running_run(run_a))
    projector = _projector(
        store,
        _Broadcast(),
        agent_run_repository=repository,
    )
    await projector.update(
        "session-001",
        RunStarted(run_id=run_a, phase=AgentRunPhase.WAITING_FOR_MODEL),
    )
    await projector.update(
        "session-001",
        ReasoningDelta(run_id=run_a, delta="stale thought"),
    )

    repository.current = _running_run(run_b)
    await projector.flush_session("session-001")

    assert await store.list_by_session_id("session-001") == []


@pytest.mark.asyncio
async def test_delayed_run_started_cannot_discard_current_pending_partial() -> None:
    """A stale Run A start cannot erase a buffered Run B partial."""
    store = InMemoryLiveEventStore()
    run_a = "a" * 32
    run_b = "b" * 32
    repository = _AgentRunRepository(_running_run(run_b))
    projector = _projector(
        store,
        _Broadcast(),
        agent_run_repository=repository,
    )
    await projector.update(
        "session-001",
        RunStarted(run_id=run_b, phase=AgentRunPhase.WAITING_FOR_MODEL),
    )
    await projector.update(
        "session-001",
        ContentDelta(run_id=run_b, delta="current", content_index=0),
    )

    await projector.update(
        "session-001",
        RunStarted(run_id=run_a, phase=AgentRunPhase.WAITING_FOR_MODEL),
    )
    await projector.flush_session("session-001")

    events = await store.list_by_session_id("session-001")
    assert len(events) == 1
    payload = events[0].payload
    assert isinstance(payload, AssistantMessagePayload)
    assert payload.content == "current"


@pytest.mark.asyncio
async def test_run_started_rechecks_authority_before_serialized_discard() -> None:
    """A delayed Run A lookup cannot discard Run B's buffered partial."""
    store = InMemoryLiveEventStore()
    run_a = "a" * 32
    run_b = "b" * 32
    repository = _BlockingFirstActiveLookupRepository(_running_run(run_a))
    projector = _projector(
        store,
        _Broadcast(),
        agent_run_repository=repository,
    )

    delayed_a = asyncio.create_task(
        projector.update(
            "session-001",
            RunStarted(run_id=run_a, phase=AgentRunPhase.WAITING_FOR_MODEL),
        )
    )
    await repository.lookup_started.wait()
    repository.current = _running_run(run_b)
    await projector.update(
        "session-001",
        RunStarted(run_id=run_b, phase=AgentRunPhase.WAITING_FOR_MODEL),
    )
    await projector.update(
        "session-001",
        ContentDelta(run_id=run_b, delta="current", content_index=0),
    )

    repository.release_lookup.set()
    await delayed_a
    await projector.flush_session("session-001")

    events = await store.list_by_session_id("session-001")
    assert len(events) == 1
    payload = events[0].payload
    assert isinstance(payload, AssistantMessagePayload)
    assert payload.content == "current"


@pytest.mark.asyncio
async def test_delta_append_is_serialized_with_run_boundary() -> None:
    """Run B activation waits for admitted Run A append, then discards it."""
    store = InMemoryLiveEventStore()
    run_a = "a" * 32
    run_b = "b" * 32
    repository = _AgentRunRepository(_running_run(run_a))
    projector = _projector(
        store,
        _Broadcast(),
        agent_run_repository=repository,
    )
    await projector.update(
        "session-001",
        RunStarted(run_id=run_a, phase=AgentRunPhase.WAITING_FOR_MODEL),
    )

    partial_batcher = cast(Any, projector)._partial_batcher
    original_buffer = partial_batcher.buffer_content_delta
    append_started = asyncio.Event()
    release_append = asyncio.Event()

    async def gated_buffer(**kwargs: object) -> bool:
        append_started.set()
        await release_append.wait()
        return await original_buffer(**kwargs)

    partial_batcher.buffer_content_delta = gated_buffer
    stale_delta = asyncio.create_task(
        projector.update(
            "session-001",
            ContentDelta(run_id=run_a, delta="stale", content_index=0),
        )
    )
    await append_started.wait()
    repository.current = _running_run(run_b)
    activate_b = asyncio.create_task(
        projector.update(
            "session-001",
            RunStarted(run_id=run_b, phase=AgentRunPhase.WAITING_FOR_MODEL),
        )
    )
    await asyncio.sleep(0)
    assert not activate_b.done()

    release_append.set()
    await stale_delta
    await activate_b
    await projector.update(
        "session-001",
        ContentDelta(run_id=run_b, delta="current", content_index=0),
    )
    await projector.flush_session("session-001")

    events = await store.list_by_session_id("session-001")
    assert len(events) == 1
    payload = events[0].payload
    assert isinstance(payload, AssistantMessagePayload)
    assert payload.content == "current"


def _live_run(run_id: str) -> ChatLiveRunState:
    """Create one live running Run projection."""
    return ChatLiveRunState(
        run_id=run_id,
        phase=AgentRunPhase.WAITING_FOR_MODEL,
        status=AgentRunStatus.RUNNING,
        inference_profile=AppliedInferenceProfile(
            model_target_label="main",
            model_display_name="Test model",
            reasoning_effort=None,
        ),
        model_call_started_at=datetime.datetime(2026, 7, 14, tzinfo=datetime.UTC),
        retry=None,
    )


@pytest.mark.asyncio
async def test_stale_terminal_event_does_not_clear_newer_run_projection() -> None:
    """Run A terminal delivery cannot clear the active Run B projection."""
    run_b = "b" * 32
    store = _LiveEventStore()
    broadcast = _Broadcast()
    projector = _projector(
        store,
        broadcast,
        current_run=_running_run(run_b),
    )
    await projector.publish_live_run_updated(
        "session-001",
        ChatLiveRunState(
            run_id=run_b,
            phase=AgentRunPhase.WAITING_FOR_MODEL,
            status=AgentRunStatus.RUNNING,
            inference_profile=AppliedInferenceProfile(
                model_target_label="main",
                model_display_name="Test model",
                reasoning_effort=None,
            ),
            model_call_started_at=datetime.datetime(2026, 7, 14, tzinfo=datetime.UTC),
            retry=None,
        ),
    )

    await projector.update("session-001", RunComplete(run_id="run-a"))
    await projector.publish_live_run_cleared("session-001", run_id="run-a")

    assert store.clear_count == 0
    assert [event[1]["type"] for event in broadcast.events] == ["live_run_updated"]
    live_run = broadcast.events[0][1]["run"]
    assert isinstance(live_run, dict)
    assert live_run["model_call_started_at"] == "2026-07-14T00:00:00+00:00"

    await projector.publish_live_run_cleared("session-001", run_id=run_b)

    assert broadcast.events[-1][1] == {
        "type": "live_run_cleared",
        "session_id": "session-001",
        "run_id": run_b,
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
async def test_live_run_clear_is_idempotent_for_same_run() -> None:
    """Repeated finalization broadcasts one live Run clear frame."""
    store = _LiveEventStore()
    broadcast = _Broadcast()
    projector = _projector(store, broadcast)
    run_id = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    await projector.publish_live_run_cleared("session-001", run_id=run_id)
    await projector.publish_live_run_cleared("session-001", run_id=run_id)

    assert broadcast.events == [
        (
            "session-001",
            {
                "type": "live_run_cleared",
                "session_id": "session-001",
                "run_id": run_id,
            },
        )
    ]


@pytest.mark.asyncio
async def test_concurrent_live_run_clear_publishes_once() -> None:
    """Overlapping finalizers emit one clear frame for the same Run."""
    store = _LiveEventStore()
    broadcast = _GatedClearBroadcast()
    projector = _projector(store, broadcast)
    run_id = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    first = asyncio.create_task(
        projector.publish_live_run_cleared("session-001", run_id=run_id)
    )
    await broadcast.clear_publish_started.wait()
    second = asyncio.create_task(
        projector.publish_live_run_cleared("session-001", run_id=run_id)
    )
    await asyncio.sleep(0)
    broadcast.release_clear_publish.set()
    await asyncio.gather(first, second)

    assert broadcast.clear_publish_attempts == 1
    assert [event[1]["type"] for event in broadcast.events] == ["live_run_cleared"]


@pytest.mark.asyncio
async def test_new_live_run_update_wins_while_old_clear_is_validating() -> None:
    """An old clear cannot pop or publish over a newer live Run update."""
    run_b = "b" * 32
    store = _LiveEventStore()
    broadcast = _Broadcast()
    repository = _BlockingAgentRunRepository()
    projector = _projector(
        store,
        broadcast,
        agent_run_repository=repository,
    )

    old_clear = asyncio.create_task(
        projector.publish_live_run_cleared("session-001", run_id="run-a")
    )
    await repository.lookup_started.wait()
    repository.current = _running_run(run_b)
    await projector.publish_live_run_updated("session-001", _live_run(run_b))
    repository.release_lookup.set()
    await old_clear

    assert [event[1]["type"] for event in broadcast.events] == ["live_run_updated"]

    # This unrelated clear would be admitted if the stale clear above had
    # incorrectly removed Run B's in-memory authority.
    await projector.publish_live_run_cleared("session-001", run_id="run-c")
    assert [event[1]["type"] for event in broadcast.events] == ["live_run_updated"]


@pytest.mark.asyncio
async def test_active_tool_calls_broadcast_without_redis_storage() -> None:
    """Active calls broadcast directly from PostgreSQL state."""
    run_id = "a" * 32
    store = _LiveEventStore()
    broadcast = _Broadcast()
    repository = _AgentRunRepository(_running_run(run_id))
    projector = _projector(
        store,
        broadcast,
        agent_run_repository=repository,
    )
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
        run_id=run_id,
        removed_call_ids=set(),
    )
    restarted_projector = _projector(
        store,
        broadcast,
        agent_run_repository=repository,
    )
    await restarted_projector.replace_active_tool_calls(
        "session-001",
        [],
        run_id=run_id,
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
async def test_old_run_tool_cleanup_cannot_remove_new_run_projection() -> None:
    """A delayed finalizer cannot clear active tools owned by a newer Run."""
    run_a = "a" * 32
    run_b = "b" * 32
    store = _LiveEventStore()
    broadcast = _Broadcast()
    repository = _AgentRunRepository(_running_run(run_a))
    projector = _projector(
        store,
        broadcast,
        agent_run_repository=repository,
    )
    call = ActiveToolCall(
        call_id="call-1",
        name="bash",
        arguments='{"cmd":"sleep"}',
        started_at=datetime.datetime(2026, 6, 4, tzinfo=datetime.UTC),
        owner_generation=1,
    )
    await projector.publish_live_run_updated("session-001", _live_run(run_a))
    await projector.replace_active_tool_calls(
        "session-001",
        [call],
        run_id=run_a,
        removed_call_ids=set(),
    )

    repository.current = _running_run(run_b)
    await projector.publish_live_run_updated("session-001", _live_run(run_b))
    await projector.replace_active_tool_calls(
        "session-001",
        [call],
        run_id=run_b,
        removed_call_ids=set(),
    )
    event_count = len(broadcast.events)

    await projector.replace_active_tool_calls(
        "session-001",
        [],
        run_id=run_a,
        removed_call_ids={"call-1"},
    )

    assert len(broadcast.events) == event_count


@pytest.mark.asyncio
async def test_stale_live_run_update_is_rejected_by_durable_authority() -> None:
    """A quarantined Run A cannot overwrite Run B's live run projection."""
    run_a = "a" * 32
    run_b = "b" * 32
    broadcast = _Broadcast()
    projector = _projector(
        _LiveEventStore(),
        broadcast,
        current_run=_running_run(run_b),
    )

    await projector.publish_live_run_updated("session-001", _live_run(run_a))
    await projector.publish_live_run_updated("session-001", _live_run(run_b))

    assert len(broadcast.events) == 1
    live_run = broadcast.events[0][1]["run"]
    assert isinstance(live_run, dict)
    assert live_run["run_id"] == run_b


@pytest.mark.asyncio
async def test_stale_active_tool_upsert_is_rejected_after_projector_restart() -> None:
    """A fresh projector uses PostgreSQL to fence a quarantined Run A call."""
    run_a = "a" * 32
    run_b = "b" * 32
    broadcast = _Broadcast()
    projector = _projector(
        _LiveEventStore(),
        broadcast,
        current_run=_running_run(run_b),
    )
    call = ActiveToolCall(
        call_id="call-1",
        name="bash",
        arguments='{"cmd":"sleep"}',
        started_at=datetime.datetime(2026, 6, 4, tzinfo=datetime.UTC),
        owner_generation=1,
    )

    await projector.replace_active_tool_calls(
        "session-001",
        [call],
        run_id=run_a,
        removed_call_ids=set(),
    )

    assert broadcast.events == []


@pytest.mark.asyncio
async def test_orphan_cleanup_requires_no_active_durable_run() -> None:
    """Stop-only cleanup cannot erase projections after a new Run starts."""
    store = _LiveEventStore()
    repository = _AgentRunRepository(_running_run("a" * 32))
    projector = _projector(
        store,
        _Broadcast(),
        agent_run_repository=repository,
    )

    assert not await projector.clear_session_if_no_active_run("session-001")
    assert store.clear_count == 0

    repository.current = None
    assert await projector.clear_session_if_no_active_run("session-001")
    assert store.clear_count == 1


@pytest.mark.asyncio
async def test_live_run_broadcast_failure_is_non_fatal() -> None:
    """Redis UI publication failure does not escape the projection boundary."""
    run_id = "a" * 32
    projector = _projector(
        _LiveEventStore(),
        _Broadcast(fail=True),
        current_run=_running_run(run_id),
    )

    await projector.publish_live_run_updated(
        "session-001",
        ChatLiveRunState(
            run_id=run_id,
            phase=AgentRunPhase.WAITING_FOR_MODEL,
            status=AgentRunStatus.RUNNING,
            inference_profile=AppliedInferenceProfile(
                model_target_label="main",
                model_display_name="Test model",
                reasoning_effort=None,
            ),
            model_call_started_at=datetime.datetime(2026, 7, 14, tzinfo=datetime.UTC),
            retry=None,
        ),
    )
    await projector.publish_live_run_cleared("session-001", run_id=run_id)
