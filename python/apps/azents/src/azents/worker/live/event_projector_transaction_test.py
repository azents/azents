"""Real PostgreSQL boundaries before volatile projection effects."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import NamedTuple

import pytest
import sqlalchemy as sa

from azents.broker.broadcast import WebSocketBroadcast
from azents.core.agent_session_data import AgentSession
from azents.core.chat_data import ChatLiveRunState
from azents.core.enums import AgentRunPhase, AgentRunStatus
from azents.core.inference_profile import AppliedInferenceProfile
from azents.engine.events.engine_events import (
    ContentDelta,
    ProviderToolActivityChanged,
    ReasoningDelta,
)
from azents.engine.events.types import AgentRunState, Event
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_execution.data import AgentRunCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.live_projection_authority import LiveProjectionAuthorityRepository
from azents.repos.live_projection_authority_test import _create_session
from azents.services.chat.live_events import (
    InMemoryLiveEventStore,
    LiveOwnerAdvance,
)
from azents.worker.live.event_projector import LiveEventProjector


class _Boundary:
    """Record SQL scopes and require detached completion at every effect."""

    def __init__(self, manager: SessionManager[WriteSession]) -> None:
        self.manager = manager
        self.sessions: list[WriteSession] = []
        self.active: list[WriteSession] = []
        self.effects: list[str] = []

    @asynccontextmanager
    async def session_manager(self) -> AsyncIterator[WriteSession]:
        async with self.manager() as session:
            self.sessions.append(session)
            self.active.append(session)
            try:
                yield session
            finally:
                self.active.remove(session)

    def check(self, effect: str) -> None:
        assert not self.active
        assert all(
            not session.write_session.in_transaction() for session in self.sessions
        )
        self.effects.append(effect)


class _Store(InMemoryLiveEventStore):
    """Verify SQL closure both before and after every owner-bound store effect."""

    def __init__(
        self, boundary: _Boundary, *, advance_failure: str | None = None
    ) -> None:
        super().__init__()
        self.boundary = boundary
        self.advance_failure = advance_failure

    async def advance_owner(
        self, session_id: str, owner_generation: int
    ) -> LiveOwnerAdvance:
        self.boundary.check("advance:before")
        if self.advance_failure == "cancel":
            raise asyncio.CancelledError()
        if self.advance_failure == "error":
            raise RuntimeError("Injected volatile advancement failure.")
        result = await super().advance_owner(session_id, owner_generation)
        self.boundary.check("advance:after")
        return result

    async def _list_for_owner(
        self, session_id: str, owner_generation: int
    ) -> list[Event]:
        self.boundary.check("list:before")
        result = await super()._list_for_owner(session_id, owner_generation)
        self.boundary.check("list:after")
        return result

    async def _get_for_owner(
        self, session_id: str, event_id: str, owner_generation: int
    ) -> Event | None:
        self.boundary.check("get:before")
        result = await super()._get_for_owner(session_id, event_id, owner_generation)
        self.boundary.check("get:after")
        return result

    async def _upsert_for_owner(self, event: Event, owner_generation: int) -> bool:
        self.boundary.check("upsert:before")
        result = await super()._upsert_for_owner(event, owner_generation)
        self.boundary.check("upsert:after")
        return result

    async def _remove_for_owner(
        self, session_id: str, event_id: str, owner_generation: int
    ) -> bool:
        self.boundary.check("remove:before")
        result = await super()._remove_for_owner(session_id, event_id, owner_generation)
        self.boundary.check("remove:after")
        return result

    async def _clear_for_owner(self, session_id: str, owner_generation: int) -> bool:
        self.boundary.check("clear:before")
        result = await super()._clear_for_owner(session_id, owner_generation)
        self.boundary.check("clear:after")
        return result


class _Broadcast(WebSocketBroadcast):
    """Verify SQL closure before and after volatile UI publication."""

    def __init__(self, boundary: _Boundary, *, failure: str | None) -> None:
        self.boundary = boundary
        self.failure = failure
        self.events: list[dict[str, object]] = []

    async def publish_live_projection(
        self, session_id: str, event_json: dict[str, object], *, owner_generation: int
    ) -> bool:
        self.boundary.check("broadcast:before")
        if self.failure == "cancel":
            raise asyncio.CancelledError()
        if self.failure == "error":
            raise RuntimeError("Injected volatile broadcast failure.")
        self.events.append(event_json)
        self.boundary.check("broadcast:after")
        return True


class _Fixture(NamedTuple):
    """Projector and concrete observable persistence/effect collaborators."""

    projector: LiveEventProjector
    boundary: _Boundary
    store: _Store
    broadcast: _Broadcast


def _fixture(
    manager: SessionManager[WriteSession],
    *,
    sessions: AgentSessionRepository,
    runs: AgentRunRepository,
    advance_failure: str | None = None,
    broadcast_failure: str | None = None,
) -> _Fixture:
    boundary = _Boundary(manager)
    store = _Store(boundary, advance_failure=advance_failure)
    broadcast = _Broadcast(boundary, failure=broadcast_failure)
    projector = LiveEventProjector(
        live_event_store=store,
        broadcast=broadcast,
        authority_repository=LiveProjectionAuthorityRepository(
            session_manager=boundary.session_manager,
            agent_session_repository=sessions,
            agent_run_repository=runs,
        ),
    )
    return _Fixture(
        projector=projector, boundary=boundary, store=store, broadcast=broadcast
    )


def _live_run(run_id: str) -> ChatLiveRunState:
    return ChatLiveRunState(
        run_id=run_id,
        phase=AgentRunPhase.WAITING_FOR_MODEL,
        status=AgentRunStatus.RUNNING,
        inference_profile=AppliedInferenceProfile(
            model_target_label="main",
            model_display_name="Test model",
            reasoning_effort=None,
            enabled_execution_options=[],
        ),
        using_fallback=False,
        model_call_started_at=None,
        retry=None,
    )


async def test_completed_owner_and_terminal_reads_precede_all_volatile_effects(
    rdb_session_manager: SessionManager[WriteSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Actual DB reads finish before reset, partial/store mutation and publication."""
    session_id = await _create_session(rdb_session_manager, handle="projection-effects")
    fixture = _fixture(
        rdb_session_manager,
        sessions=AgentSessionRepository(),
        runs=AgentRunRepository(),
    )
    projector, boundary, store, broadcast = fixture
    await projector.update(
        session_id, ContentDelta(delta="partial", content_index=0), owner_generation=0
    )
    await projector.flush_session(session_id, owner_generation=0)
    await projector.update(
        session_id,
        ReasoningDelta(
            delta="reasoning", item_id="item-1", output_index=0, summary_index=0
        ),
        owner_generation=0,
    )
    await projector.flush_session(session_id, owner_generation=0)
    await projector.update(
        session_id,
        ProviderToolActivityChanged(
            call_id="provider-1", name="web_search", status="running", arguments=None
        ),
        owner_generation=0,
    )
    await projector.discard_failed_attempt(session_id, owner_generation=0)
    await projector.publish_control_event(
        session_id, {"type": "todo_state_changed"}, owner_generation=0
    )
    await projector.publish_live_run_updated(
        session_id, _live_run("run-1"), owner_generation=0
    )
    await projector.publish_live_run_cleared(
        session_id, run_id="run-1", owner_generation=0
    )
    boundary.check("finished")
    assert boundary.sessions
    assert {
        "advance:before",
        "advance:after",
        "list:before",
        "list:after",
        "get:before",
        "get:after",
        "upsert:before",
        "upsert:after",
        "remove:before",
        "remove:after",
        "broadcast:before",
        "broadcast:after",
    }.issubset(boundary.effects)
    assert [event["type"] for event in broadcast.events][0] == "live_projection_reset"
    assert [event["type"] for event in broadcast.events][-1] == "live_run_cleared"
    await projector.clear_session(session_id, owner_generation=0)
    assert "clear:before" in boundary.effects and "clear:after" in boundary.effects
    assert await store.list_by_session_id(session_id) == []
    assert "Failed to" not in caplog.text


async def test_durable_takeover_rejects_old_effects_and_resets_new_owner_after_closure(
    rdb_session_manager: SessionManager[WriteSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """New durable authority retains the reset-removal-update order outside SQL."""
    session_id = await _create_session(
        rdb_session_manager, handle="projection-takeover"
    )
    fixture = _fixture(
        rdb_session_manager,
        sessions=AgentSessionRepository(),
        runs=AgentRunRepository(),
    )
    projector, boundary, store, broadcast = fixture
    await projector.update(
        session_id, ContentDelta(delta="old", content_index=0), owner_generation=0
    )
    await projector.flush_session(session_id, owner_generation=0)
    before = list(broadcast.events)
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == session_id)
            .values(owner_generation=1)
        )
    await projector.publish_control_event(
        session_id, {"type": "stale"}, owner_generation=0
    )
    assert broadcast.events == before
    await projector.publish_control_event(
        session_id, {"type": "fresh"}, owner_generation=1
    )
    assert [event["type"] for event in broadcast.events][-3:] == [
        "live_projection_reset",
        "live_event_removed",
        "fresh",
    ]
    assert await store.list_by_session_id(session_id) == []
    boundary.check("takeover-finished")
    assert "Failed to" not in caplog.text


@pytest.mark.parametrize("failure", ["error", "cancel"])
@pytest.mark.parametrize("stage", ["store", "broadcast"])
async def test_eligible_terminal_external_failure_still_evicts_local_generation(
    rdb_session_manager: SessionManager[WriteSession],
    failure: str,
    stage: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Eligible terminal cancellation propagates and best-effort errors stay logged."""
    session_id = await _create_session(
        rdb_session_manager, handle=f"projection-terminal-{stage}-{failure}"
    )
    fixture = _fixture(
        rdb_session_manager,
        sessions=AgentSessionRepository(),
        runs=AgentRunRepository(),
        advance_failure=failure if stage == "store" else None,
        broadcast_failure=failure if stage == "broadcast" else None,
    )
    projector, boundary, _, broadcast = fixture
    await projector.update(
        session_id, ContentDelta(delta="buffer", content_index=0), owner_generation=0
    )
    key = (session_id, 0)
    timer = projector._partial_batchers[key]._timers[session_id]
    projector._active_run_ids[key] = "run-1"
    if failure == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await projector.publish_live_run_cleared(
                session_id, run_id="run-1", owner_generation=0
            )
        assert "Failed to broadcast live run removal" not in caplog.text
    else:
        await projector.publish_live_run_cleared(
            session_id, run_id="run-1", owner_generation=0
        )
        assert "Failed to broadcast live run removal" in caplog.text
    assert key not in projector._partial_batchers
    assert key not in projector._active_run_ids
    assert key not in projector._active_tool_events
    assert timer.cancelling()
    assert broadcast.events == []
    boundary.check("terminal-failure-finished")


@pytest.mark.parametrize("failure", ["error", "cancel"])
async def test_owner_read_failure_closes_sql_without_external_effects(
    rdb_session_manager: SessionManager[WriteSession],
    failure: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Repository read failures escape to the unchanged application error boundary."""
    session_id = await _create_session(
        rdb_session_manager, handle=f"projection-read-{failure}"
    )

    class FailingSessions(AgentSessionRepository):
        async def get_by_id(
            self, session: ReadSession, agent_session_id: str
        ) -> AgentSession | None:
            await super().get_by_id(session, agent_session_id)
            if failure == "cancel":
                raise asyncio.CancelledError()
            raise ValueError("Injected owner read failure.")

    fixture = _fixture(
        rdb_session_manager, sessions=FailingSessions(), runs=AgentRunRepository()
    )
    if failure == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await fixture.projector.publish_control_event(
                session_id, {"type": "test"}, owner_generation=0
            )
        assert "Failed to broadcast live control event" not in caplog.text
    else:
        await fixture.projector.publish_control_event(
            session_id, {"type": "test"}, owner_generation=0
        )
        assert "Failed to broadcast live control event" in caplog.text
    assert fixture.broadcast.events == []
    assert fixture.boundary.effects == []
    fixture.boundary.check("read-failure-finished")


async def test_restart_and_local_run_mismatch_preserve_current_durable_projection(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Keep local mismatch short-circuit and durable current-Run-ID rules."""
    session_id = await _create_session(rdb_session_manager, handle="projection-runs")
    async with rdb_session_manager() as session:
        current = await AgentRunRepository().create(
            session,
            AgentRunCreate(
                session_id=session_id,
                scheduled_task_cycle_id=None,
                parent_agent_run_id=None,
            ),
        )
    fixture = _fixture(
        rdb_session_manager,
        sessions=AgentSessionRepository(),
        runs=AgentRunRepository(),
    )
    await fixture.projector.publish_live_run_cleared(
        session_id, run_id="0" * 32, owner_generation=0
    )
    assert fixture.broadcast.events == []
    assert len(fixture.boundary.sessions) == 1
    key = (session_id, 0)
    fixture.projector._active_run_ids[key] = "local-newer"
    await fixture.projector.publish_live_run_cleared(
        session_id, run_id=current.id, owner_generation=0
    )
    assert len(fixture.boundary.sessions) == 1
    assert fixture.projector._active_run_ids[key] == "local-newer"
    fixture.projector._active_run_ids[key] = current.id
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBAgentRun)
            .where(RDBAgentRun.id == current.id)
            .values(status=AgentRunStatus.COMPLETED)
        )
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == session_id)
            .values(owner_generation=1)
        )
    await fixture.projector.publish_live_run_cleared(
        session_id, run_id=current.id, owner_generation=0
    )
    assert key not in fixture.projector._active_run_ids
    assert fixture.broadcast.events == []
    assert len(fixture.boundary.sessions) == 3
    fixture.boundary.check("run-correlation-finished")


@pytest.mark.parametrize("failure", ["error", "cancel"])
async def test_failed_terminal_read_does_not_evict_ineligible_local_state(
    rdb_session_manager: SessionManager[WriteSession],
    failure: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Failed eligibility reads close SQL but do not advance terminal cleanup."""
    session_id = await _create_session(
        rdb_session_manager,
        handle=f"projection-terminal-read-{failure}",
    )

    class FailingRuns(AgentRunRepository):
        async def get_running_by_session_id(
            self,
            session: ReadSession,
            *,
            session_id: str,
        ) -> AgentRunState | None:
            await super().get_running_by_session_id(session, session_id=session_id)
            if failure == "cancel":
                raise asyncio.CancelledError()
            raise ValueError("Injected terminal read failure.")

    fixture = _fixture(
        rdb_session_manager,
        sessions=AgentSessionRepository(),
        runs=FailingRuns(),
    )
    key = (session_id, 0)
    fixture.projector._active_run_ids[key] = "run-1"
    if failure == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await fixture.projector.publish_live_run_cleared(
                session_id,
                run_id="run-1",
                owner_generation=0,
            )
        assert "Failed to broadcast live run removal" not in caplog.text
    else:
        await fixture.projector.publish_live_run_cleared(
            session_id,
            run_id="run-1",
            owner_generation=0,
        )
        assert "Failed to broadcast live run removal" in caplog.text
    assert fixture.projector._active_run_ids[key] == "run-1"
    assert fixture.broadcast.events == []
    assert fixture.boundary.effects == []
    fixture.boundary.check("terminal-read-failure-finished")
