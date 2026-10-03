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

from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session import SessionManager
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
            setup,
            slug=f"consumer-lock-{uuid4().hex[:8]}",
            activity_at=_NOW,
        )
        await setup.commit()
    try:
        yield source
    finally:
        async with AsyncSession(engine) as cleanup:
            await SessionLifecycleFinalizerRepository().finalize_purged_root_tree(
                cleanup,
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
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Reading Memory authority must not conflict with a Session parent FK lock."""
    repository = HistoricalMemoryRepository(rdb_session_manager)
    async with (
        _committed_source(rdb_engine) as source,
        AsyncSession(rdb_engine, expire_on_commit=False) as parent,
        AsyncSession(rdb_engine, expire_on_commit=False) as consumer,
    ):
        assert await AgentSessionRepository().lock_agent_parent_for_session(
            parent, source.session_id
        )
        snapshot = await asyncio.wait_for(
            repository.get_snapshot_consumer_in_session(
                consumer, session_id=source.session_id
            ),
            timeout=2,
        )
        assert snapshot is not None
        assert snapshot.session_id == source.session_id
        assert snapshot.agent_id == source.agent_id


@pytest.mark.parametrize("entity", ["agent", "session"])
async def test_snapshot_consumer_still_fences_authority_writers(
    rdb_engine: AsyncEngine,
    rdb_session_manager: SessionManager[AsyncSession],
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
            consumer, session_id=source.session_id
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
