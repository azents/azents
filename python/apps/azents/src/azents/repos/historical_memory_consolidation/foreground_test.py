"""Exact old-manifest authority, latest live aliases and reference-safe collection."""

import dataclasses
import datetime
import re

import pytest
import sqlalchemy as sa
from uuid6 import uuid7

from azents.core.historical_memory import HistoricalMemoryCompletion
from azents.core.historical_memory_consolidation import ConsolidationScope
from azents.core.historical_memory_snapshot import MemorySnapshotConsumer
from azents.core.vfs import (
    parse_vfs_exact_uri,
    parse_vfs_glob_pattern,
    parse_vfs_search_uri,
)
from azents.rdb.models.historical_memory import RDBHistoricalMemorySource
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationRevision,
    RDBConsolidationRevisionDependency,
)
from azents.rdb.models.toolkit_state import RDBToolkitState
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.historical_memory import HistoricalMemoryRepository
from azents.repos.historical_memory_consolidation.cleanup import (
    ConsolidationCleanupRepository,
)
from azents.repos.historical_memory_consolidation.foreground import (
    read_foreground_revision,
)
from azents.repos.memory import MemoryRepository
from azents.repos.memory_context_snapshot import MemoryContextSnapshotRepository
from azents.repos.memory_vfs.repository import MemoryVfsRepository
from azents.repos.message import MessageRepository
from azents.repos.toolkit_state import ToolkitStateRepository
from azents.services.historical_memory.context_snapshot import (
    MemoryContextSnapshotService,
)
from azents.services.memory_vfs import MemoryVfsReadBackend
from azents.services.vfs_read import VfsReadContext, VfsReadError
from azents.testing.consolidated_context import publish_context_overview
from azents.testing.consolidation import (
    ConsolidationCorpus,
    create_consolidation_source,
    seed_consolidation_corpus,
)


def _markdown(scope: ConsolidationScope, source_id: str, text: str) -> str:
    return (
        f"## Historical Context\n{text}\n\n## Source Routes\n"
        f"- azents://memory/historical/{scope.value}/{source_id}/summary.md — Details\n"
    )


async def _consumer(
    manager: SessionManager[WriteSession], source: str
) -> MemorySnapshotConsumer:
    async with manager() as session:
        result = await HistoricalMemoryRepository(
            manager
        ).get_snapshot_consumer_in_session(session, session_id=source)
        assert result is not None
        return result


def _service(manager: SessionManager[WriteSession]) -> MemoryContextSnapshotService:
    return MemoryContextSnapshotService(
        MemoryContextSnapshotRepository(
            HistoricalMemoryRepository(manager),
            MemoryRepository(),
            MessageRepository(),
            ToolkitStateRepository(),
            manager,
        )
    )


def _context(corpus: ConsolidationCorpus, *, personal: bool) -> VfsReadContext:
    return VfsReadContext(
        run_id=uuid7().hex,
        session_id=corpus.personal_source if personal else corpus.team_source,
        root_session_id=corpus.personal_source if personal else corpus.team_source,
        agent_id=corpus.team.agent_id,
        workspace_id=corpus.team.workspace_id,
        associated_user_id=corpus.personal.associated_user_id if personal else None,
        owner_generation=1,
        memory_enabled=True,
    )


async def test_independent_aliases_latest_live_read_glob_and_grep(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    manager = rdb_session_manager
    corpus = await seed_consolidation_corpus(manager)
    for key, source, text in [
        (corpus.team, corpus.team_source, "Team sentinel 한글"),
        (corpus.personal, corpus.personal_source, "Personal sentinel 日本語"),
    ]:
        await publish_context_overview(
            manager, key=key, markdown=_markdown(key.scope, source, text)
        )
    backend = MemoryVfsReadBackend(MemoryVfsRepository(manager))
    team, user = _context(corpus, personal=False), _context(corpus, personal=True)
    team_uri = "azents://memory/consolidated/team/summary.md"
    user_uri = "azents://memory/consolidated/user/summary.md"
    result = await backend.read_text(
        user, parse_vfs_exact_uri(user_uri), offset=0, limit=20000, encoding="utf-8"
    )
    assert (
        "Personal sentinel 日本語" in result.text
        and "Team sentinel 한글" not in result.text
    )
    assert "Revision:" in result.text and "Published:" in result.text
    forged = dataclasses.replace(user, associated_user_id=uuid7().hex)
    with pytest.raises(VfsReadError, match="unavailable"):
        await backend.read_text(
            forged,
            parse_vfs_exact_uri(user_uri),
            offset=0,
            limit=20000,
            encoding="utf-8",
        )
    with pytest.raises(VfsReadError, match="unavailable"):
        await backend.read_text(
            team, parse_vfs_exact_uri(user_uri), offset=0, limit=20000, encoding="utf-8"
        )
    page = await backend.glob(
        user,
        parse_vfs_glob_pattern("azents://memory/consolidated/*/summary.md"),
        exclude_patterns=(),
    )
    assert set(page.uris) == {team_uri, user_uri}
    page = await backend.glob(
        team,
        parse_vfs_glob_pattern("azents://memory/consolidated/*/summary.md"),
        exclude_patterns=(),
    )
    assert page.uris == (team_uri,)
    grep = await backend.grep(
        user,
        parse_vfs_search_uri("azents://memory/consolidated"),
        pattern=re.compile("sentinel"),
        recursive=True,
        exclude_patterns=(),
        max_matching_files=10,
        max_lines_per_file=10,
        max_searched_files=10,
        max_scanned_bytes=30000,
    )
    assert {record.path for record in grep.files} == {team_uri, user_uri}
    for uri in [
        "azents://memory/consolidated/other/summary.md",
        "azents://memory/consolidated/user/private/summary.md",
        "azents://memory/consolidated/team/draft.md",
    ]:
        with pytest.raises(VfsReadError, match="unavailable"):
            await backend.read_text(
                user, parse_vfs_exact_uri(uri), offset=0, limit=1000, encoding="utf-8"
            )


async def test_selected_old_revision_cannot_borrow_new_current_manifest(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    manager = rdb_session_manager
    corpus = await seed_consolidation_corpus(manager)
    await publish_context_overview(
        manager,
        key=corpus.team,
        markdown=_markdown(
            ConsolidationScope.TEAM, corpus.team_source, "Denied old bytes"
        ),
    )
    consumer = await _consumer(manager, corpus.personal_source)
    async with manager() as session:
        old = await read_foreground_revision(
            session, consumer=consumer, scope=ConsolidationScope.TEAM, selected=None
        )
        assert old is not None
        extra = await create_consolidation_source(
            session,
            manager=manager,
            key=corpus.team,
            summary="Allowed remainder",
            title="New source",
        )
        await AgentSessionRepository().archive(
            session, corpus.team_source, ended_at=datetime.datetime.now(datetime.UTC)
        )
    await publish_context_overview(
        manager,
        key=corpus.team,
        markdown=_markdown(ConsolidationScope.TEAM, extra, "Clean new bytes"),
    )
    async with manager() as session:
        current = await read_foreground_revision(
            session, consumer=consumer, scope=ConsolidationScope.TEAM, selected=None
        )
        assert current is not None and "Clean new bytes" in current.rendered_block
        assert (
            await read_foreground_revision(
                session, consumer=consumer, scope=ConsolidationScope.TEAM, selected=old
            )
            is None
        )
        assert (
            await session.write_session.get(RDBConsolidationRevision, old.revision_id)
            is not None
        )


async def test_purge_keeps_denial_evidence_and_recreated_grant_cannot_revive_personal(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    manager = rdb_session_manager
    corpus = await seed_consolidation_corpus(manager)
    await publish_context_overview(
        manager,
        key=corpus.personal,
        markdown=_markdown(
            ConsolidationScope.USER, corpus.personal_source, "Personal old bytes"
        ),
    )
    consumer = await _consumer(manager, corpus.personal_source)
    async with manager() as session:
        selected = await read_foreground_revision(
            session, consumer=consumer, scope=ConsolidationScope.USER, selected=None
        )
        assert selected is not None
        grant = await session.write_session.scalar(
            sa.select(RDBWorkspaceUser).where(
                RDBWorkspaceUser.user_id == corpus.personal.associated_user_id
            )
        )
        assert grant is not None
        # Rotate the durable grant exactly as revoke/recreate does, without a reader.
        grant.memory_grant_identity = uuid7().hex
    async with manager() as session:
        assert (
            await read_foreground_revision(
                session,
                consumer=consumer,
                scope=ConsolidationScope.USER,
                selected=selected,
            )
            is None
        )
        await session.write_session.execute(
            sa.delete(RDBHistoricalMemorySource).where(
                RDBHistoricalMemorySource.source_session_id == corpus.personal_source
            )
        )
    async with manager() as session:
        assert (
            await session.write_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBConsolidationRevisionDependency)
                .where(
                    RDBConsolidationRevisionDependency.revision_id
                    == selected.revision_id
                )
            )
            == 1
        )
        assert (
            await read_foreground_revision(
                session,
                consumer=consumer,
                scope=ConsolidationScope.USER,
                selected=selected,
            )
            is None
        )


async def test_collection_protects_selected_revision_and_its_full_manifest(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    manager = rdb_session_manager
    corpus = await seed_consolidation_corpus(manager)
    old = await publish_context_overview(
        manager,
        key=corpus.team,
        markdown=_markdown(
            ConsolidationScope.TEAM, corpus.team_source, "Selected old bytes"
        ),
    )
    service = _service(manager)
    assert await service.refresh_snapshot(
        session_id=corpus.team_source, after_compaction=False
    )
    now = datetime.datetime.now(datetime.UTC)
    await HistoricalMemoryRepository(manager).publish_completed(
        source_session_id=corpus.team_source,
        completion=HistoricalMemoryCompletion(
            source_activity_at=now,
            source_tail_event_id=uuid7().hex,
            prepared_at=now,
            source_title_snapshot="Changed",
            summary="New canonical source",
        ),
    )
    new = await publish_context_overview(
        manager,
        key=corpus.team,
        markdown=_markdown(
            ConsolidationScope.TEAM, corpus.team_source, "Latest live bytes"
        ),
    )
    collector = ConsolidationCleanupRepository(manager)
    assert await collector.collect_revisions(limit=10) == 0
    async with manager() as session:
        assert (
            await session.write_session.get(RDBConsolidationRevision, old) is not None
        )
        assert (
            await session.write_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBConsolidationRevisionDependency)
                .where(RDBConsolidationRevisionDependency.revision_id == old)
            )
            == 1
        )
    backend = MemoryVfsReadBackend(MemoryVfsRepository(manager))
    live = await backend.read_text(
        _context(corpus, personal=False),
        parse_vfs_exact_uri("azents://memory/consolidated/team/summary.md"),
        offset=0,
        limit=20000,
        encoding="utf-8",
    )
    assert "Latest live bytes" in live.text
    assert "Selected old bytes" in await service.prompt_for_turn(
        session_id=corpus.team_source
    )
    # No live lookup silently refreshes the automatic selection.
    async with manager() as session:
        await session.write_session.execute(
            sa.delete(RDBToolkitState).where(
                RDBToolkitState.session_id == corpus.team_source
            )
        )
    assert await collector.collect_revisions(limit=1) == 1
    async with manager() as session:
        assert await session.write_session.get(RDBConsolidationRevision, old) is None
        assert (
            await session.write_session.get(RDBConsolidationRevision, new) is not None
        )
        assert (
            await session.write_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBConsolidationRevisionDependency)
                .where(RDBConsolidationRevisionDependency.revision_id == old)
            )
            == 0
        )
