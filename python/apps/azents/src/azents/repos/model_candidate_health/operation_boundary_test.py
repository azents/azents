"""Deterministic PostgreSQL candidate claim and stale completion proofs."""

import asyncio
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.enums import ModelCandidateClaimKind
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.model_candidate_health import RDBModelCandidateHealth
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session_capabilities import create_read_write_session_manager
from azents.repos.model_candidate_health import ModelCandidateHealthRepository
from azents.repos.model_candidate_health.data import (
    CandidateHealthSettlement,
    ForegroundProbeOutcome,
    ReservationClaimOutcome,
)
from azents.repos.model_candidate_health.repository_test import (
    _expire_cooldown,
    _fixture,
)


async def _wait_for_candidate_blocker(
    engine: AsyncEngine, *, blocked_pid: int, blocker_pid: int
) -> None:
    """Poll PostgreSQL's actual lock dependency, not elapsed scheduler time."""
    async with AsyncSession(engine) as observer:
        while not await observer.scalar(
            sa.text("SELECT :blocker_pid = ANY(pg_blocking_pids(:blocked_pid))"),
            {"blocker_pid": blocker_pid, "blocked_pid": blocked_pid},
        ):
            pass


@pytest.mark.parametrize("reservation", [False, True], ids=["probe", "reservation"])
async def test_held_candidate_claim_has_one_winner_and_stale_success_is_rejected(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    reservation: bool,
) -> None:
    """A real blocked competitor sees the committed winner, not a second claim."""
    del latest_db_schema
    writes = create_read_write_session_manager(rdb_engine)
    repository = ModelCandidateHealthRepository(session_manager=writes)
    identity = await _fixture(writes, slug=f"candidate-held-{uuid4().hex}")
    competitor_task: asyncio.Task[None] | None = None
    try:
        await repository.renew_quota(identity)
        await _expire_cooldown(writes, identity)
        competitor_pids: asyncio.Queue[int] = asyncio.Queue()

        async with writes() as winner:
            winner_pid = await winner.read_session.scalar(
                sa.select(sa.func.pg_backend_pid())
            )
            assert isinstance(winner_pid, int)
            first = (
                await repository.claim_reservation_in_session(
                    winner, identity, session_id="first-session"
                )
                if reservation
                else await repository.claim_foreground_probe_in_session(
                    winner, identity, owner_id="first-operation"
                )
            )
            assert first.outcome is (
                ReservationClaimOutcome.CLAIMED
                if reservation
                else ForegroundProbeOutcome.CLAIMED
            )
            claim = first.observation.health
            assert claim is not None
            assert claim.generation == 2
            assert claim.claim_token is not None

            async def compete() -> None:
                async with writes() as competitor:
                    competitor_pid = await competitor.read_session.scalar(
                        sa.select(sa.func.pg_backend_pid())
                    )
                    assert isinstance(competitor_pid, int)
                    assert competitor_pid != winner_pid
                    await competitor_pids.put(competitor_pid)
                    second = (
                        await repository.claim_reservation_in_session(
                            competitor, identity, session_id="second-session"
                        )
                        if reservation
                        else await repository.claim_foreground_probe_in_session(
                            competitor, identity, owner_id="second-operation"
                        )
                    )
                    assert second.outcome is (
                        ReservationClaimOutcome.BUSY
                        if reservation
                        else ForegroundProbeOutcome.BUSY
                    )
                    assert second.observation.health == claim

            competitor_task = asyncio.create_task(compete())
            competitor_pid = await asyncio.wait_for(competitor_pids.get(), timeout=5)
            await asyncio.wait_for(
                _wait_for_candidate_blocker(
                    rdb_engine, blocked_pid=competitor_pid, blocker_pid=winner_pid
                ),
                timeout=5,
            )
            assert not competitor_task.done()
            await winner.write_session.commit()
            await asyncio.wait_for(competitor_task, timeout=5)

        committed = await repository.snapshot(identity)
        assert committed.health == claim
        if reservation:
            transferred = await repository.transfer_reservation(
                identity,
                expected_generation=claim.generation,
                expected_session_id="first-session",
                expected_claim_token=claim.claim_token,
                operation_id="first-operation",
            )
            assert transferred is not None
            claim = transferred.health
            assert claim.claim_token is not None
        assert claim.claim_kind is ModelCandidateClaimKind.PROBE
        assert claim.claim_owner_id == "first-operation"
        renewed = await repository.renew_quota(identity)
        assert renewed.health is not None
        assert renewed.health.generation == claim.generation + 1
        assert (
            await repository.complete_probe_success(
                identity,
                expected_generation=claim.generation,
                expected_owner_id="first-operation",
                expected_claim_token=claim.claim_token,
            )
            is CandidateHealthSettlement.STALE
        )
        retained = await repository.snapshot(identity)
        assert retained.health == renewed.health
        assert retained.health.claim_token is None
    finally:
        if competitor_task is not None and not competitor_task.done():
            competitor_task.cancel()
            await asyncio.gather(competitor_task, return_exceptions=True)
        async with writes() as cleanup:
            await cleanup.write_session.execute(
                sa.delete(RDBModelCandidateHealth).where(
                    RDBModelCandidateHealth.workspace_id == identity.workspace_id
                )
            )
            await cleanup.write_session.execute(
                sa.delete(RDBLLMProviderIntegration).where(
                    RDBLLMProviderIntegration.id == identity.llm_provider_integration_id
                )
            )
            await cleanup.write_session.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id == identity.workspace_id)
            )
