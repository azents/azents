"""Retained partial work is recoverable; denied prose is rebuilt as a whole."""

import datetime

import pytest
import sqlalchemy as sa

from azents.core.historical_memory_consolidation import (
    ConsolidationDisposition,
    ConsolidationWorkState,
)
from azents.core.historical_memory_publication import (
    ConsolidationCoverage,
    ConsolidationWorkDisposition,
)
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationDraftDependency,
    RDBConsolidationEvidence,
    RDBConsolidationUnit,
    RDBConsolidationWork,
)
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.historical_memory_consolidation.drafts import (
    ConsolidationDraftRepository,
    DraftFileChange,
)
from azents.repos.historical_memory_consolidation.ownership import (
    ConsolidationOwnershipRepository,
)
from azents.repos.historical_memory_consolidation.recovery import (
    ConsolidationRecoveryRepository,
)
from azents.repos.historical_memory_consolidation.work import (
    ConsolidationWorkRepository,
)
from azents.testing.consolidation import (
    consolidation_deadline,
    seed_consolidation_corpus,
)


@pytest.mark.parametrize("deny_restore", [False, True])
async def test_recovery_retains_authorized_draft_or_discards_entire_denied_work(
    rdb_session_manager: SessionManager[WriteSession], deny_restore: bool
) -> None:
    corpus = await seed_consolidation_corpus(rdb_session_manager)
    owners = ConsolidationOwnershipRepository(rdb_session_manager)
    claim = await owners.claim(corpus.team, deadline=consolidation_deadline())
    assert claim is not None
    work = ConsolidationWorkRepository(rdb_session_manager)
    page = await work.page(claim.principal, after_sequence=None, limit=50)
    assert len(page.entries) == 1
    drafts = ConsolidationDraftRepository(rdb_session_manager)
    observed = await drafts.observe(claim.principal, path="summary.md")
    result = await drafts.mutate(
        claim.principal,
        tool_call_id="partial",
        request_digest="a" * 64,
        expected_draft_revision_id=observed.draft_revision_id,
        expected_observation_epoch=observed.observation_epoch,
        changes=[
            DraftFileChange(
                "summary.md", observed.file_revision_id, "retained partial prose"
            )
        ],
    )
    coverage = ConsolidationCoverage(
        dispositions=(
            ConsolidationWorkDisposition(
                work_id=page.entries[0].work_id,
                action=ConsolidationDisposition.CONSIDERED,
                reason="Partial integration",
            ),
        )
    )
    await work.record_coverage(
        claim.principal,
        expected_draft_revision_id=result.draft_revision_id,
        coverage=coverage,
    )
    if deny_restore:
        async with rdb_session_manager() as session:
            await AgentSessionRepository().archive(
                session,
                corpus.team_source,
                ended_at=datetime.datetime.now(datetime.UTC),
            )
            await AgentSessionRepository().restore_tree(
                session,
                root_session_id=corpus.team_source,
                session_ids=[corpus.team_source],
            )
    checkpoint = await ConsolidationRecoveryRepository(rdb_session_manager).prepare(
        claim.principal
    )
    actual = await drafts.observe(claim.principal, path="summary.md")
    assert checkpoint.rebuilt == deny_restore
    if deny_restore:
        assert (
            actual.content is None
            and actual.draft_revision_id != result.draft_revision_id
        )
        assert checkpoint.observation_epoch > observed.observation_epoch
    else:
        assert actual.content == "retained partial prose"
        assert actual.draft_revision_id == result.draft_revision_id
    async with rdb_session_manager() as session:
        row = await session.read_session.get(
            RDBConsolidationWork, page.entries[0].work_id
        )
        assert row is not None
        assert row.state is (
            ConsolidationWorkState.PENDING
            if deny_restore
            else ConsolidationWorkState.CONSIDERED
        )
        if deny_restore:
            assert (
                row.considered_draft_id
                is row.considered_draft_revision_id
                is row.disposition
                is None
            )
            assert (
                await session.read_session.scalar(
                    sa.select(sa.func.count()).select_from(
                        RDBConsolidationDraftDependency
                    )
                )
                == 0
            )
            assert (
                await session.read_session.scalar(
                    sa.select(sa.func.count())
                    .select_from(RDBConsolidationEvidence)
                    .where(
                        RDBConsolidationEvidence.attempt_id
                        == claim.principal.attempt_id
                    )
                )
                == 0
            )


async def test_new_owner_recovers_only_draft_dependencies_not_prior_unused_exposures(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    corpus = await seed_consolidation_corpus(rdb_session_manager)
    owners = ConsolidationOwnershipRepository(rdb_session_manager)
    first = await owners.claim(corpus.team, deadline=consolidation_deadline())
    assert first is not None
    drafts = ConsolidationDraftRepository(rdb_session_manager)
    observed = await drafts.observe(first.principal, path="summary.md")
    await drafts.mutate(
        first.principal,
        tool_call_id="partial",
        request_digest="a" * 64,
        expected_draft_revision_id=observed.draft_revision_id,
        expected_observation_epoch=observed.observation_epoch,
        changes=[
            DraftFileChange(
                "summary.md",
                observed.file_revision_id,
                "permitted draft without unused exposure",
            )
        ],
    )
    # This later page influenced no file mutation; a fresh owner has no right to
    # replay its old conversation or inherit it as current attempt exposure.
    await ConsolidationWorkRepository(rdb_session_manager).page(
        first.principal, after_sequence=None, limit=50
    )
    await owners.fail(
        first.principal, failure_code="synthetic_interruption", cancelled=False
    )
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBConsolidationUnit)
            .where(RDBConsolidationUnit.agent_id == corpus.team.agent_id)
            .values(retry_at=sa.func.clock_timestamp() - datetime.timedelta(seconds=1))
        )
        await AgentSessionRepository().archive(
            session, corpus.team_source, ended_at=datetime.datetime.now(datetime.UTC)
        )
    second = await owners.claim(corpus.team, deadline=consolidation_deadline())
    assert second is not None
    checkpoint = await ConsolidationRecoveryRepository(rdb_session_manager).prepare(
        second.principal
    )
    assert not checkpoint.rebuilt
    actual = await drafts.observe(second.principal, path="summary.md")
    assert actual.content == "permitted draft without unused exposure"
    assert actual.observation_epoch == 0
