"""Actual PostgreSQL commit order is independent of work identity sequence order."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from uuid6 import uuid7

from azents.core.historical_memory_consolidation import (
    ConsolidationDisposition,
    ConsolidationWorkState,
)
from azents.core.historical_memory_publication import (
    ConsolidationCoverage,
    ConsolidationWorkDisposition,
    validate_consolidation_overview,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.historical_memory_consolidation import RDBConsolidationWork
from azents.rdb.models.session_agent import RDBSessionAgent
from azents.rdb.models.session_agent_context import RDBSessionAgentContext
from azents.rdb.models.user import RDBUser
from azents.rdb.models.workspace import RDBWorkspace
from azents.repos.historical_memory_consolidation.drafts import (
    ConsolidationDraftRepository,
    DraftFileChange,
)
from azents.repos.historical_memory_consolidation.ownership import (
    ConsolidationOwnershipRepository,
)
from azents.repos.historical_memory_consolidation.publication import (
    ConsolidationPublicationRepository,
)
from azents.repos.historical_memory_consolidation.work import (
    ConsolidationWorkRepository,
)
from azents.testing.consolidation import (
    create_consolidation_source,
    seed_consolidation_corpus,
)


async def test_lower_sequence_committing_after_publication_remains_pending(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> None:
    """A PostgreSQL identity sequence is not a transaction commit watermark."""
    factory = async_sessionmaker(rdb_engine, expire_on_commit=False)

    @asynccontextmanager
    async def manager() -> AsyncGenerator[AsyncSession, None]:
        async with factory.begin() as session:
            yield session

    corpus = await seed_consolidation_corpus(manager)
    late_transaction = factory()
    try:
        async with manager() as session:
            templates: list[RDBConsolidationWork] = []
            for index in range(2):
                source_id = await create_consolidation_source(
                    session,
                    manager=manager,
                    key=corpus.team,
                    summary="Synthetic late-commit source",
                    title=f"Synthetic commit-order source {index}",
                )
                original = await session.scalar(
                    sa.select(RDBConsolidationWork).where(
                        RDBConsolidationWork.source_session_id == source_id
                    )
                )
                assert original is not None
                templates.append(
                    RDBConsolidationWork(
                        id=uuid7().hex,
                        agent_id=original.agent_id,
                        workspace_id=original.workspace_id,
                        scope=original.scope,
                        associated_user_id=original.associated_user_id,
                        source_session_id=original.source_session_id,
                        summary_generation=original.summary_generation,
                        availability_generation=original.availability_generation,
                        evidence_hash=original.evidence_hash,
                        membership_grant_id=original.membership_grant_id,
                        kind=original.kind,
                    )
                )
                await session.delete(original)
        # Real transactions insert in sequence order and commit in reverse order.
        # Holding only work metadata leaves source/owner locks available.
        await late_transaction.begin()
        late_transaction.add(templates[0])
        await late_transaction.flush()
        async with manager() as session:
            session.add(templates[1])
            await session.flush()
        assert templates[0].sequence < templates[1].sequence
        owners = ConsolidationOwnershipRepository(manager)
        claim = await owners.claim(corpus.team)
        assert claim is not None
        work = ConsolidationWorkRepository(manager)
        page = await work.page(claim.principal, after_sequence=None, limit=50)
        ids = {entry.work_id for entry in page.entries}
        assert templates[0].id not in ids and templates[1].id in ids
        assert len(ids) == 2
        coverage = ConsolidationCoverage(
            dispositions=tuple(
                ConsolidationWorkDisposition(
                    work_id=entry.work_id,
                    action=ConsolidationDisposition.OMITTED,
                    reason="Synthetic source has no useful compact context",
                )
                for entry in page.entries
            )
        )
        drafts = ConsolidationDraftRepository(manager)
        summary = await drafts.observe(claim.principal, path="summary.md")
        journal = await drafts.observe(claim.principal, path="coverage.json")
        markdown = "## Historical Context\n\n## Source Routes\n"
        await drafts.mutate(
            claim.principal,
            tool_call_id=uuid7().hex,
            request_digest="b" * 64,
            expected_draft_revision_id=summary.draft_revision_id,
            expected_observation_epoch=summary.observation_epoch,
            changes=[
                DraftFileChange("summary.md", summary.file_revision_id, markdown),
                DraftFileChange(
                    "coverage.json",
                    journal.file_revision_id,
                    coverage.model_dump_json(),
                ),
            ],
        )
        publication = ConsolidationPublicationRepository(manager)
        frozen = await publication.freeze(claim.principal)
        await work.record_coverage(
            claim.principal,
            expected_draft_revision_id=frozen.revision_id,
            coverage=frozen.coverage,
        )
        await publication.publish(
            claim.principal,
            expected_draft_revision_id=frozen.revision_id,
            expected_observation_epoch=frozen.observation_epoch,
            overview=validate_consolidation_overview(
                key=corpus.team, markdown=frozen.markdown
            ),
        )
        await late_transaction.commit()
        async with manager() as session:
            late = await session.get(RDBConsolidationWork, templates[0].id)
            assert late is not None
            assert late.sequence < page.pass_upper_sequence
            assert late.state is ConsolidationWorkState.PENDING
            assert late.presented_attempt_id is late.published_revision_id is None
        next_claim = await owners.claim(corpus.team)
        assert next_claim is not None
        next_page = await work.page(next_claim.principal, after_sequence=None, limit=50)
        assert {entry.work_id for entry in next_page.entries} == {templates[0].id}
    finally:
        await late_transaction.close()
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
