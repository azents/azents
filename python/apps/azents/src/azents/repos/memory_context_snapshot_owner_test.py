"""Foreground aggregate operations retain durable Session owner fencing."""

import pytest
import sqlalchemy as sa

from azents.core.session_resource_authority import SessionExecutionOwner
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.toolkit_state import RDBToolkitState
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.historical_memory import HistoricalMemoryRepository
from azents.repos.memory import MemoryRepository
from azents.repos.memory_context_snapshot import MemoryContextSnapshotRepository
from azents.repos.message import MessageRepository
from azents.repos.session_execution import CanonicalExecutionOwnerGenerationStaleError
from azents.repos.toolkit_state import ToolkitStateRepository
from azents.services.historical_memory.context_snapshot import (
    MemoryContextSnapshotService,
)
from azents.testing.consolidation import seed_consolidation_corpus


async def test_takeover_keeps_descriptive_reads_but_rejects_old_owner_writes(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    manager = rdb_session_manager
    corpus = await seed_consolidation_corpus(manager)
    service = MemoryContextSnapshotService(
        MemoryContextSnapshotRepository(
            HistoricalMemoryRepository(manager),
            MemoryRepository(),
            MessageRepository(),
            ToolkitStateRepository(),
            manager,
            manager,
            owner=None,
        )
    )
    async with manager() as session:
        root = await session.write_session.get(RDBAgentSession, corpus.team_source)
        assert root is not None
        generation = root.owner_generation
    bound = service.with_owner(SessionExecutionOwner(corpus.team_source, generation))
    assert bound is not service
    assert await bound.refresh_snapshot(
        session_id=corpus.team_source, after_compaction=False
    )
    async with manager() as session:
        row = await session.write_session.scalar(
            sa.select(RDBToolkitState).where(
                RDBToolkitState.session_id == corpus.team_source,
                RDBToolkitState.toolkit_namespace == "memory",
                RDBToolkitState.state_name == "context_snapshot",
            )
        )
        assert row is not None
        snapshot_id, version, payload = row.id, row.version, row.state_json
        root = await session.write_session.get(RDBAgentSession, corpus.team_source)
        assert root is not None
        root.owner_generation = generation + 1
    assert await bound.prompt_for_turn(
        session_id=corpus.team_source
    ) == await service.prompt_for_turn(session_id=corpus.team_source)
    with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
        await bound.refresh_snapshot(
            session_id=corpus.team_source, after_compaction=False
        )
    async with manager() as session:
        row = await session.write_session.get(RDBToolkitState, snapshot_id)
        assert row is not None
        assert row.version == version and row.state_json == payload
    current = service.with_owner(
        SessionExecutionOwner(corpus.team_source, generation + 1)
    )
    assert await current.refresh_snapshot(
        session_id=corpus.team_source, after_compaction=False
    )
