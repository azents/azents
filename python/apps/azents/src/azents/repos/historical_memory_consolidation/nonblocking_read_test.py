"""Committed Memory reads remain permitted while independent writers hold rows."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

import azents.repos.memory_context_snapshot as snapshot_module
from azents.core.historical_memory_consolidation import ConsolidationScope
from azents.core.historical_memory_snapshot import (
    ConsolidatedMemorySnapshotEntry,
    MemorySnapshotConsumer,
)
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.historical_memory import RDBHistoricalMemorySource
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationRevision,
    RDBConsolidationUnit,
)
from azents.rdb.models.session_agent import RDBSessionAgent
from azents.rdb.models.user import RDBUser
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session_capabilities import (
    ReadSession,
    create_read_only_session_manager,
    create_read_write_session_manager,
)
from azents.repos.historical_memory import HistoricalMemoryRepository
from azents.repos.historical_memory_consolidation.cleanup import (
    ConsolidationCleanupRepository,
)
from azents.repos.historical_memory_consolidation.foreground import (
    read_foreground_revision,
)
from azents.repos.historical_memory_consolidation.ownership import (
    ConsolidationOwnershipRepository,
)
from azents.repos.historical_memory_consolidation.sources import (
    ConsolidationSourceRepository,
    read_source,
)
from azents.repos.memory import MemoryRepository
from azents.repos.memory_context_snapshot import MemoryContextSnapshotRepository
from azents.repos.memory_vfs.data import MemoryVfsAuthority
from azents.repos.memory_vfs.repository import MemoryVfsRepository
from azents.repos.message import MessageRepository
from azents.repos.session_lifecycle_finalizer import SessionLifecycleFinalizerRepository
from azents.repos.toolkit_state import ToolkitStateRepository
from azents.testing.consolidated_context import publish_context_overview
from azents.testing.consolidation import (
    ConsolidationCorpus,
    consolidation_deadline,
    seed_consolidation_corpus,
)


@asynccontextmanager
async def _committed_corpus(engine: AsyncEngine) -> AsyncIterator[ConsolidationCorpus]:
    writes = create_read_write_session_manager(engine)
    corpus = await seed_consolidation_corpus(writes)
    try:
        yield corpus
    finally:
        async with writes() as session:
            for source_id in (corpus.team_source, corpus.personal_source):
                await SessionLifecycleFinalizerRepository().finalize_purged_root_tree(
                    session, root_session_id=source_id, session_ids=[source_id]
                )
            await session.write_session.execute(
                sa.delete(RDBAgentRuntime).where(
                    RDBAgentRuntime.agent_id == corpus.team.agent_id
                )
            )
            await session.write_session.execute(
                sa.delete(RDBAgent).where(RDBAgent.id == corpus.team.agent_id)
            )
            await session.write_session.execute(
                sa.delete(RDBWorkspaceUser).where(
                    RDBWorkspaceUser.workspace_id == corpus.team.workspace_id
                )
            )
            await session.write_session.execute(
                sa.delete(RDBWorkspace).where(
                    RDBWorkspace.id == corpus.team.workspace_id
                )
            )
            await session.write_session.execute(
                sa.delete(RDBUser).where(
                    RDBUser.id == corpus.personal.associated_user_id
                )
            )


@pytest.mark.parametrize(
    "entity", ["agent", "grant", "root", "source", "revision", "tree"]
)
async def test_exact_selected_revision_reads_with_held_writer(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    entity: str,
) -> None:
    reads = create_read_only_session_manager(rdb_engine)
    writes = create_read_write_session_manager(rdb_engine)
    async with _committed_corpus(rdb_engine) as corpus:
        revision_id = await publish_context_overview(
            writes,
            key=corpus.personal,
            markdown=(
                "## Historical Context\nRetained personal sentinel\n\n"
                "## Source Routes\n"
                f"- azents://memory/historical/user/{corpus.personal_source}"
                "/summary.md — Details\n"
            ),
        )
        async with reads() as session:
            consumer = (
                await HistoricalMemoryRepository.get_snapshot_consumer_in_session(
                    session, session_id=corpus.personal_source
                )
            )
            assert consumer is not None
            selected = await read_foreground_revision(
                session, consumer=consumer, scope=ConsolidationScope.USER, selected=None
            )
            assert selected is not None
        contexts = MemoryContextSnapshotRepository(
            HistoricalMemoryRepository(writes),
            MemoryRepository(),
            MessageRepository(),
            ToolkitStateRepository(),
            writes,
            reads,
        )
        assert await contexts.refresh_snapshot(
            session_id=corpus.personal_source, after_compaction=False
        )
        async with reads() as session:
            generation = await session.read_session.scalar(
                sa.select(RDBAgentSession.owner_generation).where(
                    RDBAgentSession.id == corpus.personal_source
                )
            )
            assert generation is not None
        bound = contexts.with_owner(
            SessionExecutionOwner(corpus.personal_source, generation)
        )
        assert bound.read_session_manager is reads
        statements = {
            "agent": sa.select(RDBAgent.id).where(RDBAgent.id == corpus.team.agent_id),
            "tree": sa.select(RDBSessionAgent.id).where(
                RDBSessionAgent.agent_session_id == corpus.personal_source
            ),
            "grant": sa.select(RDBWorkspaceUser.id).where(
                RDBWorkspaceUser.workspace_id == corpus.personal.workspace_id,
                RDBWorkspaceUser.user_id == corpus.personal.associated_user_id,
            ),
            "root": sa.select(RDBAgentSession.id).where(
                RDBAgentSession.id == corpus.personal_source
            ),
            "source": sa.select(RDBHistoricalMemorySource.source_session_id).where(
                RDBHistoricalMemorySource.source_session_id == corpus.personal_source
            ),
            "revision": sa.select(RDBConsolidationRevision.id).where(
                RDBConsolidationRevision.id == revision_id
            ),
        }
        async with AsyncSession(rdb_engine) as writer:
            assert await writer.scalar(statements[entity].with_for_update()) is not None
            async with reads() as session:
                observed = await asyncio.wait_for(
                    read_foreground_revision(
                        session,
                        consumer=consumer,
                        scope=ConsolidationScope.USER,
                        selected=selected,
                    ),
                    timeout=2,
                )
                assert observed == selected
            prompt = await asyncio.wait_for(
                bound.prompt_for_turn(session_id=corpus.personal_source), timeout=2
            )
            assert "Retained personal sentinel" in prompt.text
            live = await asyncio.wait_for(
                MemoryVfsRepository(reads).get_consolidated(
                    MemoryVfsAuthority(
                        root_session_id=corpus.personal_source,
                        agent_id=corpus.personal.agent_id,
                        workspace_id=corpus.personal.workspace_id,
                        associated_user_id=corpus.personal.associated_user_id,
                        memory_enabled=True,
                    ),
                    scope="user",
                    max_bytes=20000,
                ),
                timeout=2,
            )
            assert live is not None and live.entry == selected
            async with reads() as session:
                if entity in {"source", "root"}:
                    source = await asyncio.wait_for(
                        read_source(
                            session,
                            key=corpus.personal,
                            source_session_id=corpus.personal_source,
                        ),
                        timeout=2,
                    )
                    assert source.source_session_id == corpus.personal_source


async def test_receipt_producer_reads_source_without_source_read_lock(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    async with _committed_corpus(rdb_engine) as corpus:
        claim = await ConsolidationOwnershipRepository(writes).claim(
            corpus.team, deadline=consolidation_deadline()
        )
        assert claim is not None
        async with AsyncSession(rdb_engine) as writer:
            source = await writer.scalar(
                sa.select(RDBHistoricalMemorySource)
                .where(
                    RDBHistoricalMemorySource.source_session_id == corpus.team_source
                )
                .with_for_update()
            )
            assert source is not None
            result = await asyncio.wait_for(
                ConsolidationSourceRepository(writes).read(
                    claim.principal,
                    source_session_id=corpus.team_source,
                    offset=0,
                    max_bytes=1000,
                ),
                timeout=2,
            )
            assert result.version.summary_generation == source.summary_generation
            assert result.version.evidence_hash == source.evidence_hash
            assert result.observation_epoch > 0
            assert "sentinel" in result.text


@pytest.mark.parametrize(
    "denial", ["missing-source", "collected-revision", "null-hash", "disabled-agent"]
)
async def test_missing_or_denied_exact_reference_is_unavailable(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    denial: str,
) -> None:
    reads = create_read_only_session_manager(rdb_engine)
    writes = create_read_write_session_manager(rdb_engine)
    async with _committed_corpus(rdb_engine) as corpus:
        await publish_context_overview(
            writes,
            key=corpus.team,
            markdown=(
                "## Historical Context\nOld selected sentinel\n\n## Source Routes\n"
                f"- azents://memory/historical/team/{corpus.team_source}"
                "/summary.md — Details\n"
            ),
        )
        async with reads() as session:
            consumer = (
                await HistoricalMemoryRepository.get_snapshot_consumer_in_session(
                    session, session_id=corpus.team_source
                )
            )
            assert consumer is not None
            selected = await read_foreground_revision(
                session, consumer=consumer, scope=ConsolidationScope.TEAM, selected=None
            )
            assert selected is not None
        async with writes() as session:
            if denial == "missing-source":
                await session.write_session.execute(
                    sa.delete(RDBHistoricalMemorySource).where(
                        RDBHistoricalMemorySource.source_session_id
                        == corpus.team_source
                    )
                )
            elif denial == "collected-revision":
                await session.write_session.execute(
                    sa.update(RDBConsolidationUnit)
                    .where(RDBConsolidationUnit.id == selected.unit_id)
                    .values(published_revision_id=None)
                )
                await session.write_session.execute(
                    sa.delete(RDBConsolidationRevision).where(
                        RDBConsolidationRevision.id == selected.revision_id
                    )
                )
            elif denial == "null-hash":
                await session.write_session.execute(
                    sa.update(RDBHistoricalMemorySource)
                    .where(
                        RDBHistoricalMemorySource.source_session_id
                        == corpus.team_source
                    )
                    .values(evidence_hash=None)
                )
            else:
                await session.write_session.execute(
                    sa.update(RDBAgent)
                    .where(RDBAgent.id == corpus.team.agent_id)
                    .values(memory_enabled=False)
                )
        async with reads() as session:
            assert (
                await read_foreground_revision(
                    session,
                    consumer=consumer,
                    scope=ConsolidationScope.TEAM,
                    selected=selected,
                )
                is None
            )


async def test_collection_between_selection_and_snapshot_save_is_unavailable(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reads = create_read_only_session_manager(rdb_engine)
    writes = create_read_write_session_manager(rdb_engine)
    async with _committed_corpus(rdb_engine) as corpus:
        revision_id = await publish_context_overview(
            writes,
            key=corpus.team,
            markdown=(
                "## Historical Context\nCollected selection\n\n## Source Routes\n"
                f"- azents://memory/historical/team/{corpus.team_source}"
                "/summary.md — Details\n"
            ),
        )
        collected = False

        async def select_then_collect(
            session: ReadSession,
            *,
            consumer: MemorySnapshotConsumer,
            scope: ConsolidationScope,
            selected: ConsolidatedMemorySnapshotEntry | None,
        ) -> ConsolidatedMemorySnapshotEntry | None:
            nonlocal collected
            entry = await read_foreground_revision(
                session, consumer=consumer, scope=scope, selected=selected
            )
            if entry is not None and not collected:
                # A committed publication can move the pointer after selection.
                # Collection then races before this descriptive reference persists.
                async with writes() as writer:
                    await writer.write_session.execute(
                        sa.update(RDBConsolidationUnit)
                        .where(RDBConsolidationUnit.id == entry.unit_id)
                        .values(published_revision_id=None)
                    )
                assert (
                    await ConsolidationCleanupRepository(writes).collect_revisions(
                        limit=100
                    )
                    >= 1
                )
                collected = True
            return entry

        monkeypatch.setattr(
            snapshot_module, "read_foreground_revision", select_then_collect
        )
        contexts = MemoryContextSnapshotRepository(
            HistoricalMemoryRepository(writes),
            MemoryRepository(),
            MessageRepository(),
            ToolkitStateRepository(),
            writes,
            reads,
        )
        assert await contexts.refresh_snapshot(
            session_id=corpus.team_source, after_compaction=False
        )
        assert collected
        async with reads() as session:
            assert (
                await session.read_session.get(RDBConsolidationRevision, revision_id)
                is None
            )
        prompt = await contexts.prompt_for_turn(session_id=corpus.team_source)
        assert "Collected selection" not in prompt.text
