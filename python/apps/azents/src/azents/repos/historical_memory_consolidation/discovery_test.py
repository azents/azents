"""Exact-unit discovery, lease/backoff gates and unavailable metadata retirement."""

import datetime
import logging

import pytest
import sqlalchemy as sa

from azents.core.historical_memory_consolidation import ConsolidationWorkState
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationUnit,
    RDBConsolidationWork,
)
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.historical_memory_consolidation.discovery import (
    ConsolidationDiscoveryRepository,
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


async def test_three_failed_attempts_warn_and_back_off_without_acknowledging_work(
    rdb_session_manager: SessionManager[WriteSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    corpus = await seed_consolidation_corpus(rdb_session_manager)
    owners = ConsolidationOwnershipRepository(rdb_session_manager)
    caplog.set_level(logging.WARNING)
    for index in range(3):
        claim = await owners.claim(corpus.team, deadline=consolidation_deadline())
        assert claim is not None
        await owners.fail(
            claim.principal, failure_code="synthetic_failure", cancelled=False
        )
        async with rdb_session_manager() as session:
            unit = await session.read_session.get(RDBConsolidationUnit, claim.unit_id)
            assert unit is not None and unit.retry_at is not None
            assert unit.no_progress_count == index + 1
            assert unit.retry_at > datetime.datetime.now(datetime.UTC)
            if index < 2:
                unit.retry_at = datetime.datetime.now(datetime.UTC)
    assert any(
        record.message
        == ("Historical consolidation attempts made no completed coverage progress")
        for record in caplog.records
    )
    async with rdb_session_manager() as session:
        states = list(
            await session.read_session.scalars(
                sa.select(RDBConsolidationWork.state).where(
                    RDBConsolidationWork.agent_id == corpus.team.agent_id
                )
            )
        )
        assert states and all(
            state is ConsolidationWorkState.PENDING for state in states
        )


async def test_discovery_coalesces_exact_units_and_honors_owner_retry_and_eligibility(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    corpus = await seed_consolidation_corpus(rdb_session_manager)
    repository = ConsolidationDiscoveryRepository(rdb_session_manager)
    assert set(await repository.list_due(agent_id=None, limit=25)) == {
        corpus.team,
        corpus.personal,
    }
    ownership = ConsolidationOwnershipRepository(rdb_session_manager)
    claim = await ownership.claim(corpus.team, deadline=consolidation_deadline())
    assert claim is not None
    assert await repository.list_due(agent_id=corpus.team.agent_id, limit=25) == (
        corpus.personal,
    )
    await ownership.fail(
        claim.principal, failure_code="synthetic_retry", cancelled=False
    )
    assert await repository.list_due(agent_id=corpus.team.agent_id, limit=25) == (
        corpus.personal,
    )
    async with rdb_session_manager() as session:
        unit = await session.read_session.get(RDBConsolidationUnit, claim.unit_id)
        assert unit is not None
        unit.retry_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            seconds=1
        )
    assert set(await repository.list_due(agent_id=corpus.team.agent_id, limit=25)) == {
        corpus.team,
        corpus.personal,
    }
    async with rdb_session_manager() as session:
        agent = await session.read_session.get(RDBAgent, corpus.team.agent_id)
        assert agent is not None
        agent.memory_enabled = False
    assert await repository.list_due(agent_id=None, limit=25) == ()


async def test_personal_membership_loss_waits_without_peer_unit_or_model_admission(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    corpus = await seed_consolidation_corpus(rdb_session_manager)
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.delete(RDBWorkspaceUser).where(
                RDBWorkspaceUser.workspace_id == corpus.personal.workspace_id,
                RDBWorkspaceUser.user_id == corpus.personal.associated_user_id,
            )
        )
    assert await ConsolidationDiscoveryRepository(rdb_session_manager).list_due(
        agent_id=None, limit=25
    ) == (corpus.team,)


async def test_denied_source_metadata_retires_without_model_coverage_acknowledgement(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    corpus = await seed_consolidation_corpus(rdb_session_manager)
    async with rdb_session_manager() as session:
        await AgentSessionRepository().archive(
            session, corpus.team_source, ended_at=datetime.datetime.now(datetime.UTC)
        )
    ownership = ConsolidationOwnershipRepository(rdb_session_manager)
    claim = await ownership.claim(corpus.team, deadline=consolidation_deadline())
    assert claim is not None
    await ConsolidationRecoveryRepository(rdb_session_manager).prepare(claim.principal)
    work = ConsolidationWorkRepository(rdb_session_manager)
    assert await work.retire_obsolete_pending(claim.principal) == 2
    assert await work.retire_obsolete_pending(claim.principal) == 0
    assert (
        await work.page(claim.principal, after_sequence=None, limit=50)
    ).entries == ()
    async with rdb_session_manager() as session:
        rows = list(
            await session.read_session.scalars(
                sa.select(RDBConsolidationWork).where(
                    RDBConsolidationWork.source_session_id == corpus.team_source
                )
            )
        )
        assert len(rows) == 2 and all(
            row.state is ConsolidationWorkState.SUPERSEDED for row in rows
        )
        assert all(row.disposition is row.published_revision_id is None for row in rows)
