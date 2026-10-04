"""Verify Memory consumer locks coexist with Session FK parent protection."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.agent_session_data import AgentSessionCreate
from azents.core.enums import AgentSessionProductMode
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.historical_memory import HistoricalMemoryRepository
from azents.repos.historical_memory.repository_test import (
    _NOW,
    _create_source,
    _SourceFixture,
)
from azents.repos.session_lifecycle_finalizer import SessionLifecycleFinalizerRepository


@asynccontextmanager
async def _committed_source(
    engine: AsyncEngine,
) -> AsyncIterator[_SourceFixture]:
    """Own committed fixture rows across independent connections and remove them."""
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        source = await _create_source(
            ReadWriteSession(setup),
            slug=f"consumer-lock-{uuid4().hex[:8]}",
            activity_at=_NOW,
        )
        await setup.commit()
    try:
        yield source
    finally:
        async with AsyncSession(engine) as cleanup:
            await SessionLifecycleFinalizerRepository().finalize_purged_root_tree(
                ReadWriteSession(cleanup),
                root_session_id=source.session_id,
                session_ids=[source.session_id],
            )
            await cleanup.execute(
                sa.delete(RDBAgentRuntime).where(
                    RDBAgentRuntime.agent_id == source.agent_id
                )
            )
            await cleanup.execute(
                sa.delete(RDBAgent).where(RDBAgent.id == source.agent_id)
            )
            await cleanup.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id == source.workspace_id)
            )
            await cleanup.commit()


async def test_snapshot_consumer_coexists_with_agent_parent_key_share(
    rdb_engine: AsyncEngine,
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Reading Memory authority must not conflict with a Session parent FK lock."""
    repository = HistoricalMemoryRepository(rdb_session_manager)
    async with (
        _committed_source(rdb_engine) as source,
        AsyncSession(rdb_engine, expire_on_commit=False) as parent,
        AsyncSession(rdb_engine, expire_on_commit=False) as consumer,
    ):
        assert await AgentSessionRepository().lock_agent_parent_for_session(
            ReadWriteSession(parent), source.session_id
        )
        snapshot = await asyncio.wait_for(
            repository.get_snapshot_consumer_in_session(
                ReadWriteSession(consumer), session_id=source.session_id
            ),
            timeout=2,
        )
        assert snapshot is not None
        assert snapshot.session_id == source.session_id
        assert snapshot.agent_id == source.agent_id


@asynccontextmanager
async def _committed_peer(
    engine: AsyncEngine, source: _SourceFixture
) -> AsyncIterator[str]:
    """Own a second root Session sharing the first source's Agent authority."""
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        peer = await AgentSessionRepository().create(
            ReadWriteSession(setup),
            AgentSessionCreate(
                workspace_id=source.workspace_id,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                agent_id=source.agent_id,
                title="Concurrent Memory consumer",
            ),
        )
        await setup.commit()
    try:
        yield peer.id
    finally:
        async with AsyncSession(engine) as cleanup:
            await SessionLifecycleFinalizerRepository().finalize_purged_root_tree(
                ReadWriteSession(cleanup),
                root_session_id=peer.id,
                session_ids=[peer.id],
            )
            await cleanup.commit()


@pytest.mark.parametrize("distinct_sessions", [False, True])
async def test_concurrent_snapshot_consumers_keep_parent_fk_locks(
    rdb_engine: AsyncEngine,
    rdb_session_manager: SessionManager[WriteSession],
    distinct_sessions: bool,
) -> None:
    """Two canonical parent-lock holders must not deadlock during Memory access."""
    repository = HistoricalMemoryRepository(rdb_session_manager)
    ready = asyncio.Barrier(2)
    async with _committed_source(rdb_engine) as source:
        async with _committed_peer(rdb_engine, source) as peer_id:

            async def consume(session_id: str) -> None:
                async with AsyncSession(rdb_engine, expire_on_commit=False) as session:
                    assert await AgentSessionRepository().lock_agent_parent_for_session(
                        ReadWriteSession(session), session_id
                    )
                    await ready.wait()
                    snapshot = await repository.get_snapshot_consumer_in_session(
                        ReadWriteSession(session), session_id=session_id
                    )
                    assert snapshot is not None
                    assert snapshot.session_id == session_id
                    assert snapshot.agent_id == source.agent_id
                    await session.commit()

            async def run_consumers() -> None:
                async with asyncio.TaskGroup() as tasks:
                    tasks.create_task(consume(source.session_id))
                    tasks.create_task(
                        consume(peer_id if distinct_sessions else source.session_id)
                    )

            await asyncio.wait_for(run_consumers(), timeout=5)


@pytest.mark.parametrize("entity", ["agent", "session"])
async def test_snapshot_consumer_still_fences_authority_writers(
    rdb_engine: AsyncEngine,
    rdb_session_manager: SessionManager[WriteSession],
    entity: Literal["agent", "session"],
) -> None:
    """FK-compatible reads still exclude changes to Memory and Session authority."""
    repository = HistoricalMemoryRepository(rdb_session_manager)
    async with (
        _committed_source(rdb_engine) as source,
        AsyncSession(rdb_engine, expire_on_commit=False) as consumer,
        AsyncSession(rdb_engine, expire_on_commit=False) as writer,
    ):
        snapshot = await repository.get_snapshot_consumer_in_session(
            ReadWriteSession(consumer), session_id=source.session_id
        )
        assert snapshot is not None
        statement = (
            sa.select(RDBAgent.id).where(RDBAgent.id == source.agent_id)
            if entity == "agent"
            else sa.select(RDBAgentSession.id).where(
                RDBAgentSession.id == source.session_id
            )
        )
        with pytest.raises(OperationalError, match="could not obtain lock"):
            await writer.execute(statement.with_for_update(key_share=True, nowait=True))
