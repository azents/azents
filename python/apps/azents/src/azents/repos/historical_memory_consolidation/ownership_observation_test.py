"""Read-only ownership observation under concurrent lifecycle writers."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationUnit,
)
from azents.rdb.models.user import RDBUser
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import (
    WriteSession,
    create_read_write_session_manager,
)
from azents.repos.historical_memory_consolidation.authority import (
    ConsolidationAuthorityError,
    unit_predicate,
)
from azents.repos.historical_memory_consolidation.ownership import (
    ConsolidationOwnershipRepository,
)
from azents.repos.session_lifecycle_finalizer import SessionLifecycleFinalizerRepository
from azents.testing.consolidation import (
    ConsolidationCorpus,
    consolidation_deadline,
    seed_consolidation_corpus,
)


@asynccontextmanager
async def _committed_corpus(
    engine: AsyncEngine,
) -> AsyncIterator[ConsolidationCorpus]:
    """Expose committed fixture rows to independent lock and observation sessions."""
    writes = create_read_write_session_manager(engine)
    corpus = await seed_consolidation_corpus(writes)
    try:
        yield corpus
    finally:
        async with writes() as session:
            for source_id in (corpus.team_source, corpus.personal_source):
                await SessionLifecycleFinalizerRepository().finalize_purged_root_tree(
                    session,
                    root_session_id=source_id,
                    session_ids=[source_id],
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


async def test_validate_observes_exact_personal_owner_while_lifecycle_rows_are_held(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Validation does not wait on Agent, grant, or unit writer locks."""
    del latest_db_schema
    writes: SessionManager[WriteSession] = create_read_write_session_manager(rdb_engine)
    async with _committed_corpus(rdb_engine) as corpus:
        ownership = ConsolidationOwnershipRepository(writes)
        claim = await ownership.claim(
            corpus.personal,
            deadline=consolidation_deadline(),
        )
        assert claim is not None

        lock_acquired = asyncio.Event()
        release_locks = asyncio.Event()

        async def hold_lifecycle_rows() -> None:
            async with writes() as session:
                agent_id = await session.write_session.scalar(
                    sa.select(RDBAgent.id)
                    .where(
                        RDBAgent.id == corpus.personal.agent_id,
                        RDBAgent.workspace_id == corpus.personal.workspace_id,
                    )
                    .with_for_update()
                )
                assert agent_id is not None
                grant_id = await session.write_session.scalar(
                    sa.select(RDBWorkspaceUser.id)
                    .where(
                        RDBWorkspaceUser.workspace_id == corpus.personal.workspace_id,
                        RDBWorkspaceUser.user_id == corpus.personal.associated_user_id,
                    )
                    .with_for_update()
                )
                assert grant_id is not None
                unit_id = await session.write_session.scalar(
                    sa.select(RDBConsolidationUnit.id)
                    .where(unit_predicate(corpus.personal))
                    .with_for_update()
                )
                assert unit_id == claim.unit_id
                lock_acquired.set()
                await release_locks.wait()

        holder = asyncio.create_task(hold_lifecycle_rows())
        try:
            await asyncio.wait_for(lock_acquired.wait(), timeout=5)
            await asyncio.wait_for(ownership.validate(claim.principal), timeout=1)
        finally:
            release_locks.set()
            await holder

        async with writes() as session:
            unit = await session.write_session.get(
                RDBConsolidationUnit,
                claim.unit_id,
            )
            assert unit is not None
            unit.owner_generation += 1

        with pytest.raises(ConsolidationAuthorityError):
            await ownership.validate(claim.principal)
