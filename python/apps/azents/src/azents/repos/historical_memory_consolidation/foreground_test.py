"""Scope-only current results, original public lookup and boundary byte retention."""

import dataclasses
import datetime
import re

import pytest
import sqlalchemy as sa
from uuid6 import uuid7

from azents.core.historical_memory_consolidation import ConsolidationScope
from azents.core.historical_memory_snapshot import MemorySnapshotConsumer
from azents.core.vfs import (
    parse_vfs_exact_uri,
    parse_vfs_glob_pattern,
    parse_vfs_search_uri,
)
from azents.rdb.models.historical_memory import RDBHistoricalMemorySource
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.historical_memory import HistoricalMemoryRepository
from azents.repos.historical_memory_consolidation.foreground import read_current_result
from azents.repos.memory_vfs.repository import MemoryVfsRepository
from azents.services.memory_vfs import MemoryVfsReadBackend
from azents.services.vfs_read import VfsReadContext, VfsReadError
from azents.testing.consolidated_context import publish_context_overview
from azents.testing.consolidation import ConsolidationCorpus, seed_consolidation_corpus


def _markdown(scope: ConsolidationScope, source_id: str, text: str) -> str:
    return text


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


async def _consumer(
    manager: SessionManager[WriteSession], source: str
) -> MemorySnapshotConsumer:
    async with manager() as session:
        result = await HistoricalMemoryRepository.get_snapshot_consumer_in_session(
            session, session_id=source
        )
        assert result is not None
        return result


async def test_selected_bytes_survive_source_purge_without_source_manifest_queries(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    manager = rdb_session_manager
    corpus = await seed_consolidation_corpus(manager)
    await publish_context_overview(
        manager, key=corpus.team, markdown="Old accepted bytes"
    )
    consumer = await _consumer(manager, corpus.personal_source)
    async with manager() as session:
        selected = await read_current_result(
            session, consumer=consumer, scope=ConsolidationScope.TEAM, selected=None
        )
    assert selected is not None
    async with manager() as session:
        await session.write_session.execute(
            sa.delete(RDBHistoricalMemorySource).where(
                RDBHistoricalMemorySource.source_session_id == corpus.team_source
            )
        )
    await publish_context_overview(
        manager, key=corpus.team, markdown="New current bytes"
    )
    async with manager() as session:
        retained = await read_current_result(
            session, consumer=consumer, scope=ConsolidationScope.TEAM, selected=selected
        )
        current = await read_current_result(
            session, consumer=consumer, scope=ConsolidationScope.TEAM, selected=None
        )
    assert retained == selected and "Old accepted bytes" in retained.rendered_block
    assert current is not None and "New current bytes" in current.rendered_block


async def test_personal_scope_membership_loss_fails_closed_without_affecting_team(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    manager = rdb_session_manager
    corpus = await seed_consolidation_corpus(manager)
    await publish_context_overview(manager, key=corpus.team, markdown="Team")
    await publish_context_overview(manager, key=corpus.personal, markdown="Private")
    consumer = await _consumer(manager, corpus.personal_source)
    async with manager() as session:
        selected = await read_current_result(
            session, consumer=consumer, scope=ConsolidationScope.USER, selected=None
        )
    assert selected is not None
    async with manager() as session:
        await session.write_session.execute(
            sa.delete(RDBWorkspaceUser).where(
                RDBWorkspaceUser.workspace_id == corpus.team.workspace_id,
                RDBWorkspaceUser.user_id == corpus.personal.associated_user_id,
            )
        )
    async with manager() as session:
        assert (
            await read_current_result(
                session,
                consumer=consumer,
                scope=ConsolidationScope.USER,
                selected=selected,
            )
            is None
        )
        assert (
            await read_current_result(
                session, consumer=consumer, scope=ConsolidationScope.TEAM, selected=None
            )
            is not None
        )
        forged = consumer.model_copy(update={"associated_user_id": uuid7().hex})
        assert (
            await read_current_result(
                session, consumer=forged, scope=ConsolidationScope.USER, selected=None
            )
            is None
        )


async def test_public_consumer_archive_blocks_even_selected_scope_bytes(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    manager = rdb_session_manager
    corpus = await seed_consolidation_corpus(manager)
    await publish_context_overview(manager, key=corpus.team, markdown="Scoped result")
    consumer = await _consumer(manager, corpus.team_source)
    async with manager() as session:
        selected = await read_current_result(
            session, consumer=consumer, scope=ConsolidationScope.TEAM, selected=None
        )
        await AgentSessionRepository().archive(
            session, corpus.team_source, ended_at=datetime.datetime.now(datetime.UTC)
        )
    async with manager() as session:
        assert (
            await read_current_result(
                session,
                consumer=consumer,
                scope=ConsolidationScope.TEAM,
                selected=selected,
            )
            is None
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
    assert "Revision:" not in result.text and "Published:" in result.text
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
