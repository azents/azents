"""Bounded full-summary searches and exact personal inventory isolation."""

import re

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from azents.core.enums import WorkspaceUserRole
from azents.core.historical_memory_consolidation import (
    ConsolidationScope,
    ConsolidationUnitKey,
)
from azents.core.vfs import parse_vfs_glob_pattern, parse_vfs_search_uri
from azents.rdb.models.historical_memory_consolidation import RDBConsolidationEvidence
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.repos.historical_memory_consolidation.ownership import (
    ConsolidationOwnershipRepository,
)
from azents.repos.historical_memory_consolidation.sources import (
    ConsolidationSourceRepository,
)
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.services.historical_memory.draft_vfs import ConsolidationVfsObservations
from azents.services.historical_memory.source_vfs import ConsolidationSourceVfsBackend
from azents.services.vfs_read import VfsReadError
from azents.testing.consolidation import (
    create_consolidation_source,
    seed_consolidation_corpus,
)
from azents.testing.consolidation_vfs import bind_consolidation_test_vfs


async def test_search_finds_tail_beyond_one_result_chunk_and_honors_scan_bound(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    binding = await bind_consolidation_test_vfs(rdb_session_manager)
    async with rdb_session_manager() as session:
        source_id = await create_consolidation_source(
            session,
            manager=rdb_session_manager,
            key=binding.principal.unit,
            summary="z" * 13000 + "\nneedle\n",
            title="Long source",
        )
        await session.commit()
    location = parse_vfs_search_uri(binding.source.source_uri(source_id))
    full = await binding.source.grep(
        binding.principal,
        location,
        pattern=re.compile("needle"),
        recursive=True,
        exclude_patterns=(),
        max_matching_files=50,
        max_lines_per_file=10,
        max_searched_files=50,
        max_scanned_bytes=20000,
    )
    assert full.matched_file_count == 1 and not full.truncated
    assert full.files[0].lines[0].text == "needle"
    prefix = await binding.source.grep(
        binding.principal,
        location,
        pattern=re.compile("needle"),
        recursive=True,
        exclude_patterns=(),
        max_matching_files=50,
        max_lines_per_file=10,
        max_searched_files=50,
        max_scanned_bytes=100,
    )
    assert prefix.matched_file_count == 0 and prefix.truncated
    assert prefix.stopped_reason == "scanned_byte_limit"


async def test_personal_inventory_excludes_team_and_another_personal_user(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    corpus = await seed_consolidation_corpus(rdb_session_manager)
    async with rdb_session_manager() as session:
        user = await UserRepository().create(
            session, UserCreate(email=f"{uuid7().hex}@example.test")
        )
        session.add(
            RDBWorkspaceUser(
                workspace_id=corpus.personal.workspace_id,
                user_id=user.id,
                name="Other",
                role=WorkspaceUserRole.MEMBER,
            )
        )
        await session.flush()
        other_key = ConsolidationUnitKey(
            workspace_id=corpus.personal.workspace_id,
            agent_id=corpus.personal.agent_id,
            scope=ConsolidationScope.USER,
            associated_user_id=user.id,
        )
        other_id = await create_consolidation_source(
            session,
            manager=rdb_session_manager,
            key=other_key,
            summary="OTHER_USER_SENTINEL",
            title="Other private source",
        )
        await session.commit()
    claim = await ConsolidationOwnershipRepository(rdb_session_manager).claim(
        corpus.personal
    )
    assert claim is not None
    backend = ConsolidationSourceVfsBackend(
        ConsolidationSourceRepository(rdb_session_manager),
        ConsolidationVfsObservations(claim.principal),
    )
    inventory = await backend.read_text(
        claim.principal,
        parse_vfs_search_uri("azents://memory/inventory/README.md"),
        offset=0,
        limit=10000,
        encoding="utf-8",
    )
    assert corpus.personal_source in inventory.text
    assert corpus.team_source not in inventory.text and other_id not in inventory.text
    for denied in (other_id, corpus.team_source):
        with pytest.raises(VfsReadError):
            await backend.read_text(
                claim.principal,
                parse_vfs_search_uri(backend.source_uri(denied)),
                offset=0,
                limit=10000,
                encoding="utf-8",
            )


async def test_exact_source_after_first_page_and_literal_prefix_are_not_starved(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    binding = await bind_consolidation_test_vfs(rdb_session_manager)
    ids: list[str] = []
    async with rdb_session_manager() as session:
        for index in range(55):
            ids.append(
                await create_consolidation_source(
                    session,
                    manager=rdb_session_manager,
                    key=binding.principal.unit,
                    summary=f"target-{index}",
                    title=f"Source {index}",
                )
            )
        await session.commit()
    target = max(ids)
    uri = binding.source.source_uri(target)
    result = await binding.source.grep(
        binding.principal,
        parse_vfs_search_uri(uri),
        pattern=re.compile("target-"),
        recursive=False,
        exclude_patterns=(),
        max_matching_files=1,
        max_lines_per_file=1,
        max_searched_files=1,
        max_scanned_bytes=12000,
    )
    assert result.matched_file_count == result.searched_file_count == 1
    assert result.files[0].path == uri and not result.truncated
    for pattern in (
        uri,
        uri.replace("/summary.md", "/**"),
        uri.replace(target, target + "*"),
    ):
        exact = await binding.source.glob(
            binding.principal,
            parse_vfs_glob_pattern(pattern),
            exclude_patterns=(),
        )
        assert exact.uris == (uri,) and not exact.truncated
    async with rdb_session_manager() as session:
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBConsolidationEvidence)
                .where(
                    RDBConsolidationEvidence.attempt_id == binding.principal.attempt_id
                )
            )
            == 1
        )
    broad = await binding.source.glob(
        binding.principal,
        parse_vfs_glob_pattern("azents://memory/**"),
        exclude_patterns=(),
    )
    assert len(broad.uris) == 50 and broad.truncated
    assert broad.stopped_reason == "inventory_page_limit"
    broad_search = await binding.source.grep(
        binding.principal,
        parse_vfs_search_uri("azents://memory"),
        pattern=re.compile("target-"),
        recursive=True,
        exclude_patterns=(),
        max_matching_files=1,
        max_lines_per_file=1,
        max_searched_files=1,
        max_scanned_bytes=12000,
    )
    assert broad_search.searched_file_count == 1 and broad_search.truncated


async def test_narrowed_source_queries_preserve_scope_and_agent_denial(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    binding = await bind_consolidation_test_vfs(rdb_session_manager)
    other = await seed_consolidation_corpus(rdb_session_manager)
    for source_id in (other.team_source, other.personal_source):
        uri = binding.source.source_uri(source_id)
        glob = await binding.source.glob(
            binding.principal, parse_vfs_search_uri(uri), exclude_patterns=()
        )
        assert glob.uris == ()
        grep = await binding.source.grep(
            binding.principal,
            parse_vfs_search_uri(uri),
            pattern=re.compile("sentinel"),
            recursive=False,
            exclude_patterns=(),
            max_matching_files=1,
            max_lines_per_file=1,
            max_searched_files=1,
            max_scanned_bytes=12000,
        )
        assert grep.searched_file_count == grep.matched_file_count == 0
    with pytest.raises(VfsReadError):
        await binding.source.glob(
            binding.principal,
            parse_vfs_glob_pattern("azents://memory/historical/user/**"),
            exclude_patterns=(),
        )
