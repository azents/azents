"""Concurrent source opportunities share the ordinary Session admission fence."""

import asyncio
import datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

import azents.repos.routine.judgment_inbox as inbox_module
from azents.core.routine import RoutineScope
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.rdb.session_capabilities import (
    WriteSession,
    create_read_write_session_manager,
)
from azents.repos.routine.judgment_inbox_test import repository, subject
from azents.testing.committed_fixture_cleanup import committed_fixture_graph


async def test_competing_ticks_commit_one_input_and_one_generic_inbox_action(
    rdb_engine: AsyncEngine, latest_db_schema: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    del latest_db_schema
    metadata = sa.MetaData()
    async with rdb_engine.connect() as connection:
        await connection.run_sync(metadata.reflect)
    manager = create_read_write_session_manager(rdb_engine)
    async with committed_fixture_graph(rdb_engine, metadata):
        scope = await subject(manager)
        inbox = repository(manager)
        now = datetime.datetime(2026, 10, 18, tzinfo=datetime.UTC)
        first_fenced = asyncio.Event()
        second_entered = asyncio.Event()
        release_first = asyncio.Event()
        original = inbox_module.fence_routine_scope
        arrivals = 0

        async def fence(
            session: WriteSession,
            *,
            scope: RoutineScope,
            owner: SessionExecutionOwner | None,
        ) -> None:
            nonlocal arrivals
            arrivals += 1
            ordinal = arrivals
            if ordinal == 2:
                second_entered.set()
            await original(session, scope=scope, owner=owner)
            if ordinal == 1:
                first_fenced.set()
                await release_first.wait()

        monkeypatch.setattr(inbox_module, "fence_routine_scope", fence)
        async with asyncio.timeout(10):
            async with asyncio.TaskGroup() as tasks:
                first = tasks.create_task(inbox.admit_tick(scope=scope, now=now))
                await first_fenced.wait()
                second = tasks.create_task(inbox.admit_tick(scope=scope, now=now))
                await second_entered.wait()
                release_first.set()
        outcomes = [first.result(), second.result()]
        assert sum(item is not None for item in outcomes) == 1
        async with manager() as session:
            check = await inbox.states.get_check(session, scope=scope)
            assert check is not None
            assert check.state.queued_judgment_id is not None
            assert check.state.last_tick_at == now
            assert check.state.last_action_at is None
            assert len(check.state.source_inputs) == 1
            assert len(check.state.source_inputs[0].events) == 1
