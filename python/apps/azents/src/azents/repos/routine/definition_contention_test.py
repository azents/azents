"""Concurrent duplicate creation respects the ordinary Session mutation fence."""

import asyncio

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

import azents.repos.routine.operations as operations_module
from azents.core.routine import RoutineScope
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.rdb.session_capabilities import (
    WriteSession,
    create_read_write_session_manager,
)
from azents.repos.routine.persistence_test import _content, _operations, _subject
from azents.testing.committed_fixture_cleanup import committed_fixture_graph


async def test_concurrent_same_slug_creates_one_definition_and_rejects_second(
    rdb_engine: AsyncEngine, latest_db_schema: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    del latest_db_schema
    metadata = sa.MetaData()
    async with rdb_engine.connect() as connection:
        await connection.run_sync(metadata.reflect)
    manager = create_read_write_session_manager(rdb_engine)
    async with committed_fixture_graph(rdb_engine, metadata):
        async with manager() as session:
            scope = await _subject(session)
        operations = _operations(manager)
        first_fenced = asyncio.Event()
        second_entered = asyncio.Event()
        release_first = asyncio.Event()
        original = operations_module.fence_routine_scope
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

        async def create() -> str:
            try:
                definition = await operations.create(
                    scope=scope, content=_content(), owner=None
                )
            except ValueError as error:
                return str(error)
            return definition.slug

        monkeypatch.setattr(operations_module, "fence_routine_scope", fence)
        async with asyncio.timeout(10):
            async with asyncio.TaskGroup() as tasks:
                first = tasks.create_task(create())
                await first_fenced.wait()
                second = tasks.create_task(create())
                await second_entered.wait()
                release_first.set()
        assert first.result() == "release-news"
        assert second.result() == (
            "Routine slug 'release-news' already exists in this Session."
        )
        definitions = await operations.list_routines(scope=scope)
        assert len(definitions) == 1
        assert definitions[0].content == _content()
