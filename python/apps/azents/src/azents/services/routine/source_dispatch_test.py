"""Source dispatch admits ordinary inbox work without executing a judgment model."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock

import pytest
import sqlalchemy as sa

from azents.broker.types import SessionBroker, SessionWakeUp
from azents.core.routine import RoutineScope, RoutineUnavailable
from azents.core.routine_execution import RoutineCheckState
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.routine.judgment_inbox import RoutineJudgmentInboxRepository
from azents.repos.routine.judgment_inbox_test import repository, subject
from azents.repos.routine.persistence_test import _content, _operations, _subject
from azents.repos.routine.source_dispatch import RoutineSourceRepository
from azents.services.routine.source_dispatch import RoutineSourceDispatcher

NOW = datetime.datetime(2026, 10, 18, tzinfo=datetime.UTC)
DEADLINE = NOW + datetime.timedelta(minutes=2)


async def test_pages_due_roots_and_publishes_only_after_admission_commits(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    open_scopes = 0

    @asynccontextmanager
    async def observed() -> AsyncGenerator[WriteSession, None]:
        nonlocal open_scopes
        async with rdb_session_manager() as session:
            open_scopes += 1
            try:
                yield session
            finally:
                open_scopes -= 1

    scopes = [await subject(observed) for _ in range(3)]
    await _operations(observed).create(
        scope=scopes[0],
        content=_content().model_copy(update={"title": "Second Routine"}),
        owner=None,
    )
    inbox = repository(observed)
    sources = RoutineSourceRepository(session_manager=observed)
    broker = Mock(spec=SessionBroker)
    wakes: list[SessionWakeUp] = []

    async def send(message: SessionWakeUp) -> None:
        assert open_scopes == 0
        wakes.append(message)

    broker.send_message = AsyncMock(side_effect=send)
    dispatcher = RoutineSourceDispatcher(
        sources=sources, inbox=inbox, broker=broker, clock=lambda: NOW, batch_size=1
    )
    async with observed() as session:
        for scope in scopes:
            assert await inbox.states.get_check(session, scope=scope) is None
    summary = await dispatcher.dispatch_once(now=NOW, deadline=DEADLINE)
    assert summary.checked == summary.enqueued == 3
    assert summary.unavailable == 0 and not summary.deadline_reached
    assert {item.session_id for item in wakes} == {item.session_id for item in scopes}
    assert open_scopes == 0
    assert await sources.list_due_scopes(now=NOW, limit=64) == []
    queued: list[str] = []
    async with observed() as session:
        for scope in scopes:
            check = await inbox.states.get_check(session, scope=scope)
            assert check is not None and check.state.queued_judgment_id is not None
            assert check.state.last_tick_at == NOW
            assert len(check.state.source_inputs) == (2 if scope == scopes[0] else 1)
            assert all(len(source.events) == 1 for source in check.state.source_inputs)
            queued.append(check.state.queued_judgment_id)
        assert (
            await session.read_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBAgentRun)
                .where(
                    RDBAgentRun.session_id.in_([scope.session_id for scope in scopes])
                )
            )
            == 0
        )
    repeated = await dispatcher.dispatch_once(now=NOW, deadline=DEADLINE)
    assert repeated.checked == repeated.enqueued == 0
    next_tick = NOW + datetime.timedelta(minutes=30)
    coalesced = await dispatcher.dispatch_once(
        now=next_tick, deadline=next_tick + datetime.timedelta(minutes=2)
    )
    assert coalesced.checked == 3 and coalesced.enqueued == 0
    assert len(wakes) == 3
    async with observed() as session:
        for scope, original in zip(scopes, queued, strict=True):
            check = await inbox.states.get_check(session, scope=scope)
            assert check is not None and check.state.queued_judgment_id == original
            assert all(len(source.events) == 2 for source in check.state.source_inputs)


async def test_due_selection_excludes_stopped_empty_and_recent_roots(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    due = await subject(rdb_session_manager)
    recent = await subject(rdb_session_manager)
    stopped = await subject(rdb_session_manager)
    inbox = repository(rdb_session_manager)
    async with rdb_session_manager() as session:
        await _subject(session)
        target = await session.write_session.get(RDBAgentSession, stopped.session_id)
        assert target is not None
        target.stop_requested_at = NOW
        await inbox.states.save_check(
            session,
            scope=recent,
            state=RoutineCheckState(
                last_tick_at=NOW - datetime.timedelta(minutes=29),
                last_action_at=None,
                source_inputs=(),
                queued_judgment_id=None,
            ),
            expected_version=None,
        )
    sources = RoutineSourceRepository(session_manager=rdb_session_manager)
    assert await sources.list_due_scopes(now=NOW, limit=64) == [due]
    both = await sources.list_due_scopes(
        now=NOW + datetime.timedelta(minutes=1), limit=64
    )
    assert {item.session_id for item in both} == {due.session_id, recent.session_id}


async def test_wake_failure_preserves_committed_action_and_is_not_swallowed(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    scope = await subject(rdb_session_manager)
    inbox = repository(rdb_session_manager)
    sources = RoutineSourceRepository(session_manager=rdb_session_manager)
    broker = Mock(spec=SessionBroker)
    broker.send_message = AsyncMock(side_effect=OSError("Synthetic broker failure"))
    dispatcher = RoutineSourceDispatcher(
        sources=sources, inbox=inbox, broker=broker, clock=lambda: NOW, batch_size=1
    )
    with pytest.raises(OSError, match="Synthetic broker failure"):
        await dispatcher.dispatch_once(now=NOW, deadline=DEADLINE)
    async with rdb_session_manager() as session:
        check = await inbox.states.get_check(session, scope=scope)
        assert check is not None and check.state.queued_judgment_id is not None
        assert check.state.last_tick_at == NOW
    assert await sources.list_due_scopes(now=NOW, limit=64) == []
    repeated = await dispatcher.dispatch_once(now=NOW, deadline=DEADLINE)
    assert repeated.checked == repeated.enqueued == 0
    broker.send_message.assert_awaited_once()


async def test_existing_scheduler_deadline_bounds_admission_without_a_new_cursor(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    scopes = [await subject(rdb_session_manager) for _ in range(2)]
    inbox = repository(rdb_session_manager)
    sources = RoutineSourceRepository(session_manager=rdb_session_manager)
    times = iter([NOW, NOW, DEADLINE])
    broker = Mock(spec=SessionBroker)
    dispatcher = RoutineSourceDispatcher(
        sources=sources,
        inbox=inbox,
        broker=broker,
        clock=lambda: next(times),
        batch_size=2,
    )
    summary = await dispatcher.dispatch_once(now=NOW, deadline=DEADLINE)
    assert summary.deadline_reached
    assert summary.checked == summary.enqueued == 1
    broker.send_message.assert_awaited_once()
    remaining = await sources.list_due_scopes(now=NOW, limit=64)
    assert len(remaining) == 1
    assert remaining[0].session_id in {scope.session_id for scope in scopes}
    empty_pass = RoutineSourceDispatcher(
        sources=sources,
        inbox=inbox,
        broker=broker,
        clock=lambda: DEADLINE,
        batch_size=2,
    )
    expired = await empty_pass.dispatch_once(now=NOW, deadline=DEADLINE)
    assert expired.deadline_reached and expired.checked == expired.enqueued == 0
    assert await sources.list_due_scopes(now=NOW, limit=64) == remaining


async def test_root_retiring_between_scan_and_admission_is_skipped() -> None:
    scope = RoutineScope("workspace", "agent", "session")
    sources = Mock(spec=RoutineSourceRepository)
    sources.list_due_scopes = AsyncMock(side_effect=[[scope], []])
    inbox = Mock(spec=RoutineJudgmentInboxRepository)
    inbox.admit_tick = AsyncMock(side_effect=RoutineUnavailable("Session retired."))
    broker = Mock(spec=SessionBroker)
    dispatcher = RoutineSourceDispatcher(
        sources=sources, inbox=inbox, broker=broker, clock=lambda: NOW, batch_size=1
    )
    summary = await dispatcher.dispatch_once(now=NOW, deadline=DEADLINE)
    assert summary.unavailable == 1
    assert summary.checked == summary.enqueued == 0
    assert not summary.deadline_reached
    broker.send_message.assert_not_awaited()
