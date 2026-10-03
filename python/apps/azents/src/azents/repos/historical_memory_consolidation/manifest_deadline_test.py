"""Complete-manifest query bounds and real PostgreSQL deadline rollback evidence."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from uuid6 import uuid7

from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.historical_memory import RDBHistoricalMemorySource
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationAttempt,
    RDBConsolidationDraft,
    RDBConsolidationDraftDependency,
    RDBConsolidationDraftFile,
    RDBConsolidationEvidence,
    RDBConsolidationMutationReceipt,
    RDBConsolidationUnit,
)
from azents.rdb.models.session_agent import RDBSessionAgent
from azents.rdb.models.session_agent_context import RDBSessionAgentContext
from azents.rdb.models.user import RDBUser
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session import SessionManager
from azents.repos.historical_memory_consolidation.authority import (
    ConsolidationAuthorityBusyError,
    ConsolidationAuthorityError,
    ConsolidationDeadlineError,
    consolidation_job_session,
)
from azents.repos.historical_memory_consolidation.drafts import (
    ConsolidationDraftRepository,
    DraftFileChange,
)
from azents.repos.historical_memory_consolidation.ownership import (
    ConsolidationOwnershipRepository,
)
from azents.repos.historical_memory_consolidation.sources import (
    ConsolidationSourceRepository,
)
from azents.testing.consolidation import (
    create_consolidation_source,
    seed_consolidation_corpus,
)


@pytest.mark.parametrize("source_count", [1, 64])
async def test_complete_manifest_has_constant_queries_and_deduplicated_locks(
    rdb_engine: AsyncEngine,
    rdb_session_manager: SessionManager[AsyncSession],
    source_count: int,
) -> None:
    corpus = await seed_consolidation_corpus(rdb_session_manager)
    claim = await ConsolidationOwnershipRepository(rdb_session_manager).claim(
        corpus.team
    )
    assert claim is not None
    drafts = ConsolidationDraftRepository(rdb_session_manager)
    await drafts.observe(claim.principal, path="summary.md")
    async with rdb_session_manager() as session:
        draft = await session.scalar(sa.select(RDBConsolidationDraft))
        assert draft is not None
        ids = [corpus.team_source]
        for index in range(source_count - 1):
            ids.append(
                await create_consolidation_source(
                    session,
                    manager=rdb_session_manager,
                    key=corpus.team,
                    summary="current evidence",
                    title=f"Source {index}",
                )
            )
        await session.execute(
            sa.update(RDBHistoricalMemorySource)
            .where(RDBHistoricalMemorySource.source_session_id.in_(ids))
            .values(summary_generation=17)
        )
        for source_id in ids:
            for generation in range(1, 17):
                session.add(
                    RDBConsolidationEvidence(
                        id=uuid7().hex,
                        attempt_id=claim.principal.attempt_id,
                        source_session_id=source_id,
                        summary_generation=generation,
                        evidence_hash="a" * 64,
                        availability_generation=1,
                        membership_grant_id=None,
                    )
                )
                if generation <= 8:
                    session.add(
                        RDBConsolidationDraftDependency(
                            id=uuid7().hex,
                            draft_id=draft.id,
                            source_session_id=source_id,
                            summary_generation=generation,
                            evidence_hash="a" * 64,
                            availability_generation=1,
                            membership_grant_id=None,
                        )
                    )
        await session.commit()
    statements: list[str] = []

    def capture(*args: object) -> None:
        statement = args[2]
        assert isinstance(statement, str)
        statements.append(statement)

    event.listen(rdb_engine.sync_engine, "before_cursor_execute", capture)
    try:
        observation = await drafts.observe(claim.principal, path="summary.md")
    finally:
        event.remove(rdb_engine.sync_engine, "before_cursor_execute", capture)
    checks = [query for query in statements if "complete_draft_influence" in query]
    assert len(checks) == 3
    assert sum("FOR SHARE NOWAIT" in query for query in checks) == 2
    assert all("SELECT DISTINCT" in query for query in checks[:2])
    assert len(statements) <= 20
    statements.clear()
    event.listen(rdb_engine.sync_engine, "before_cursor_execute", capture)
    try:
        await drafts.mutate(
            claim.principal,
            tool_call_id="complete-manifest",
            request_digest="a" * 64,
            expected_draft_revision_id=observation.draft_revision_id,
            expected_observation_epoch=observation.observation_epoch,
            changes=[
                DraftFileChange(
                    "summary.md", observation.file_revision_id, "bounded draft"
                )
            ],
        )
    finally:
        event.remove(rdb_engine.sync_engine, "before_cursor_execute", capture)
    # All generations are copied for every source, never a page/current-ID cap.
    copies = [
        query
        for query in statements
        if "INSERT INTO historical_consolidation_draft_dependencies" in query
    ]
    assert len(copies) == 1
    async with rdb_session_manager() as session:
        count = await session.scalar(
            sa.select(sa.func.count()).select_from(RDBConsolidationDraftDependency)
        )
        assert count == source_count * 16
        await session.execute(
            sa.update(RDBHistoricalMemorySource)
            .where(RDBHistoricalMemorySource.source_session_id == ids[-1])
            .values(availability_generation=2)
        )
        await session.commit()
    with pytest.raises(ConsolidationAuthorityError):
        await drafts.replay_receipt(
            claim.principal,
            tool_call_id="complete-manifest",
            request_digest="a" * 64,
        )


@pytest.mark.parametrize("deadline", ["statement", "operation"])
async def test_deadline_rolls_back_files_receipts_and_releases_fence(
    rdb_engine: AsyncEngine, latest_db_schema: None, deadline: str
) -> None:
    factory = async_sessionmaker(rdb_engine, expire_on_commit=False)

    @asynccontextmanager
    async def manager() -> AsyncGenerator[AsyncSession, None]:
        async with factory.begin() as session:
            yield session

    corpus = await seed_consolidation_corpus(manager)
    try:
        claim = await ConsolidationOwnershipRepository(manager).claim(corpus.team)
        assert claim is not None
        await ConsolidationSourceRepository(manager).read(
            claim.principal,
            source_session_id=corpus.team_source,
            offset=0,
            max_bytes=12000,
        )
        drafts = ConsolidationDraftRepository(manager)
        before = await drafts.observe(claim.principal, path="summary.md")
        created = await drafts.mutate(
            claim.principal,
            tool_call_id="before-deadline",
            request_digest="a" * 64,
            expected_draft_revision_id=before.draft_revision_id,
            expected_observation_epoch=before.observation_epoch,
            changes=[
                DraftFileChange("summary.md", before.file_revision_id, "preserved")
            ],
        )
        async with manager() as holder:
            await holder.scalar(
                sa.select(RDBHistoricalMemorySource)
                .where(
                    RDBHistoricalMemorySource.source_session_id == corpus.team_source
                )
                .with_for_update()
            )
            with pytest.raises(ConsolidationAuthorityBusyError):
                await drafts.observe(claim.principal, path="summary.md")
        # Rejected nonwaiting manifest checks release the owner fence for renewal.
        assert await ConsolidationOwnershipRepository(manager).renew(claim.principal)
        async with manager() as session:
            await session.execute(
                sa.update(RDBConsolidationAttempt)
                .where(RDBConsolidationAttempt.id == claim.principal.attempt_id)
                .values(
                    deadline_at=sa.func.clock_timestamp()
                    + datetime.timedelta(seconds=1 if deadline == "statement" else 0.2)
                )
            )
        with pytest.raises(ConsolidationDeadlineError, match="deadline"):
            async with consolidation_job_session(manager, claim.principal) as job:
                file = await job.session.scalar(
                    sa.select(RDBConsolidationDraftFile).where(
                        RDBConsolidationDraftFile.draft_id.in_(
                            sa.select(RDBConsolidationDraft.id).where(
                                RDBConsolidationDraft.unit_id == job.owner.unit.id
                            )
                        )
                    )
                )
                assert file is not None
                file.content = "must roll back"
                job.session.add(
                    RDBConsolidationMutationReceipt(
                        attempt_id=claim.principal.attempt_id,
                        tool_call_id="timed-out",
                        request_digest="b" * 64,
                        result_json=created.model_dump(mode="json"),
                    )
                )
                await job.session.flush()
                # Exercise server cancellation before the operation timer, then
                # the operation timer with server cancellation disabled. Elapsed
                # time is the contract here, not a test-ordering mechanism.
                await job.session.execute(
                    sa.select(
                        sa.func.set_config(
                            "statement_timeout",
                            "10" if deadline == "statement" else "0",
                            True,
                        )
                    )
                )
                await job.session.execute(sa.select(sa.func.pg_sleep(2)))
        async with manager() as session:
            file = await session.scalar(
                sa.select(RDBConsolidationDraftFile).where(
                    RDBConsolidationDraftFile.draft_id.in_(
                        sa.select(RDBConsolidationDraft.id).where(
                            RDBConsolidationDraft.unit_id.in_(
                                sa.select(RDBConsolidationUnit.id).where(
                                    RDBConsolidationUnit.agent_id
                                    == corpus.team.agent_id
                                )
                            )
                        )
                    )
                )
            )
            assert file is not None and file.content == "preserved"
            assert (
                await session.get(
                    RDBConsolidationMutationReceipt,
                    (claim.principal.attempt_id, "timed-out"),
                )
                is None
            )
            # An independent transaction immediately reacquires the released fence.
            assert (
                await session.scalar(
                    sa.select(RDBConsolidationUnit)
                    .where(RDBConsolidationUnit.agent_id == corpus.team.agent_id)
                    .with_for_update(nowait=True)
                )
                is not None
            )
    finally:
        async with manager() as session:
            await session.execute(
                sa.update(RDBSessionAgentContext)
                .where(RDBSessionAgentContext.agent_id == corpus.team.agent_id)
                .values(root_session_agent_id=None)
            )
            await session.execute(
                sa.delete(RDBSessionAgent).where(
                    RDBSessionAgent.agent_session_id.in_(
                        sa.select(RDBAgentSession.id).where(
                            RDBAgentSession.agent_id == corpus.team.agent_id
                        )
                    )
                )
            )
            await session.execute(
                sa.delete(RDBSessionAgentContext).where(
                    RDBSessionAgentContext.agent_id == corpus.team.agent_id
                )
            )
            await session.execute(
                sa.delete(RDBAgentSession).where(
                    RDBAgentSession.agent_id == corpus.team.agent_id
                )
            )
            await session.execute(
                sa.delete(RDBAgentRuntime).where(
                    RDBAgentRuntime.agent_id == corpus.team.agent_id
                )
            )
            await session.execute(
                sa.delete(RDBAgent).where(RDBAgent.id == corpus.team.agent_id)
            )
            await session.execute(
                sa.delete(RDBWorkspace).where(
                    RDBWorkspace.id == corpus.team.workspace_id
                )
            )
            await session.execute(
                sa.delete(RDBUser).where(
                    RDBUser.id == corpus.personal.associated_user_id
                )
            )
