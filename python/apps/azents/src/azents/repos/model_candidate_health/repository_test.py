"""PostgreSQL model candidate health authority tests."""

import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import LLMProvider, ModelCandidateClaimKind
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.model_candidate_health import RDBModelCandidateHealth
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session import SessionManager
from azents.repos.model_candidate_health import ModelCandidateHealthRepository
from azents.repos.model_candidate_health.data import (
    CandidateHealthSettlement,
    ForegroundProbeOutcome,
    ModelCandidateHealthStatus,
    ModelCandidateIdentity,
    ReservationClaimOutcome,
)


async def _fixture(
    session_manager: SessionManager[AsyncSession],
    *,
    slug: str,
) -> ModelCandidateIdentity:
    async with session_manager() as session:
        workspace = RDBWorkspace(name=slug, handle=slug)
        session.add(workspace)
        await session.flush()
        integration = RDBLLMProviderIntegration(
            workspace_id=workspace.id,
            provider=LLMProvider.OPENAI,
            name=slug,
            encrypted_credentials="test",
            config=None,
            enabled=True,
            catalog_configuration_version=1,
        )
        session.add(integration)
        await session.flush()
        return ModelCandidateIdentity(
            workspace_id=workspace.id,
            llm_provider_integration_id=integration.id,
            model_identifier="gpt-health-test",
        )


def _repository(
    session_manager: SessionManager[AsyncSession],
) -> ModelCandidateHealthRepository:
    return ModelCandidateHealthRepository(session_manager=session_manager)


async def _expire_cooldown(
    session_manager: SessionManager[AsyncSession],
    identity: ModelCandidateIdentity,
) -> None:
    async with session_manager() as session:
        await session.execute(
            sa.update(RDBModelCandidateHealth)
            .where(
                RDBModelCandidateHealth.workspace_id == identity.workspace_id,
                RDBModelCandidateHealth.llm_provider_integration_id
                == identity.llm_provider_integration_id,
                RDBModelCandidateHealth.model_identifier == identity.model_identifier,
            )
            .values(
                cooldown_until=sa.func.clock_timestamp()
                - sa.text("INTERVAL '1 second'")
            )
        )


async def _expire_claim(
    session_manager: SessionManager[AsyncSession],
    identity: ModelCandidateIdentity,
) -> None:
    async with session_manager() as session:
        await session.execute(
            sa.update(RDBModelCandidateHealth)
            .where(
                RDBModelCandidateHealth.workspace_id == identity.workspace_id,
                RDBModelCandidateHealth.llm_provider_integration_id
                == identity.llm_provider_integration_id,
                RDBModelCandidateHealth.model_identifier == identity.model_identifier,
            )
            .values(
                claim_until=sa.func.clock_timestamp() - sa.text("INTERVAL '1 second'")
            )
        )


async def test_quota_renews_generation_and_clears_reservation(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A newer quota generation immediately revokes an older reservation."""
    identity = await _fixture(rdb_session_manager, slug="candidate-health-renew")
    repository = _repository(rdb_session_manager)

    first = await repository.renew_quota(identity)
    assert first.status is ModelCandidateHealthStatus.COOLDOWN
    assert first.health is not None
    assert first.health.generation == 1
    assert first.health.cooldown_until - first.server_time == datetime.timedelta(
        minutes=5
    )

    reserved = await repository.claim_reservation(identity, session_id="a" * 32)
    assert reserved.outcome is ReservationClaimOutcome.CLAIMED
    assert reserved.observation.health is not None
    assert reserved.observation.health.generation == 2

    renewed = await repository.renew_quota(identity)
    assert renewed.health is not None
    assert renewed.health.generation == 3
    assert renewed.health.claim_kind is None
    assert renewed.health.claim_owner_id is None
    assert renewed.health.claim_token is None
    assert renewed.health.claim_until is None


async def test_foreground_probe_single_flight_and_stale_success_fence(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Only one foreground probe wins and stale success cannot clear newer quota."""
    identity = await _fixture(rdb_session_manager, slug="candidate-health-probe")
    repository = _repository(rdb_session_manager)
    await repository.renew_quota(identity)
    await _expire_cooldown(rdb_session_manager, identity)

    first = await repository.claim_foreground_probe(identity, owner_id="b" * 32)
    assert first.outcome is ForegroundProbeOutcome.CLAIMED
    assert first.observation.health is not None
    probe = first.observation.health
    assert probe.generation == 2
    assert probe.claim_kind is ModelCandidateClaimKind.PROBE
    assert probe.claim_token is not None

    busy = await repository.claim_foreground_probe(identity, owner_id="c" * 32)
    assert busy.outcome is ForegroundProbeOutcome.BUSY

    settlement, renewed = await repository.renew_claimed_quota(
        identity,
        expected_generation=probe.generation,
        expected_claim_kind=ModelCandidateClaimKind.PROBE,
        expected_owner_id="b" * 32,
        expected_claim_token=probe.claim_token,
    )
    assert settlement is CandidateHealthSettlement.APPLIED
    assert renewed.health is not None
    assert renewed.health.generation == 3

    stale_success = await repository.complete_probe_success(
        identity,
        expected_generation=probe.generation,
        expected_owner_id="b" * 32,
        expected_claim_token=probe.claim_token,
    )
    assert stale_success is CandidateHealthSettlement.STALE
    assert (await repository.snapshot(identity)).health is not None


async def test_background_never_claims_expired_health(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Background reads continue to skip until a foreground probe proves recovery."""
    identity = await _fixture(rdb_session_manager, slug="candidate-health-background")
    repository = _repository(rdb_session_manager)
    await repository.renew_quota(identity)
    await _expire_cooldown(rdb_session_manager, identity)

    first = await repository.snapshot_for_background(identity)
    second = await repository.snapshot_for_background(identity)
    assert first.status is ModelCandidateHealthStatus.RECOVERY_PENDING
    assert second.status is ModelCandidateHealthStatus.RECOVERY_PENDING
    assert first.health is not None
    assert second.health is not None
    assert first.health.generation == second.health.generation == 1
    assert first.health.claim_kind is None
    assert second.health.claim_kind is None


async def test_reservation_idempotency_transfer_and_success(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """One Session may repeat reserve and transfer its exact claim to a probe."""
    identity = await _fixture(rdb_session_manager, slug="candidate-health-reservation")
    repository = _repository(rdb_session_manager)
    await repository.renew_quota(identity)

    claimed = await repository.claim_reservation(identity, session_id="d" * 32)
    assert claimed.outcome is ReservationClaimOutcome.CLAIMED
    assert claimed.observation.health is not None
    reservation = claimed.observation.health
    assert reservation.claim_token is not None

    repeated = await repository.claim_reservation(identity, session_id="d" * 32)
    assert repeated.outcome is ReservationClaimOutcome.IDEMPOTENT
    assert repeated.observation.health is not None
    assert repeated.observation.health.claim_token == reservation.claim_token

    other = await repository.claim_reservation(identity, session_id="e" * 32)
    assert other.outcome is ReservationClaimOutcome.BUSY

    transferred = await repository.transfer_reservation(
        identity,
        expected_generation=reservation.generation,
        expected_session_id="d" * 32,
        expected_claim_token=reservation.claim_token,
        operation_id="f" * 32,
    )
    assert transferred is not None
    assert transferred.health.generation == reservation.generation
    assert transferred.health.claim_kind is ModelCandidateClaimKind.PROBE
    assert transferred.health.claim_owner_id == "f" * 32
    assert transferred.health.claim_token is not None

    success = await repository.complete_probe_success(
        identity,
        expected_generation=transferred.health.generation,
        expected_owner_id="f" * 32,
        expected_claim_token=transferred.health.claim_token,
    )
    assert success is CandidateHealthSettlement.APPLIED
    assert (
        await repository.snapshot(identity)
    ).status is ModelCandidateHealthStatus.AVAILABLE


async def test_cancel_and_expiry_are_owner_generation_fenced(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Stale cancellation and premature expiry cannot release a current claim."""
    identity = await _fixture(rdb_session_manager, slug="candidate-health-settlement")
    repository = _repository(rdb_session_manager)
    await repository.renew_quota(identity)
    claimed = await repository.claim_reservation(identity, session_id="1" * 32)
    assert claimed.observation.health is not None
    reservation = claimed.observation.health
    assert reservation.claim_token is not None

    assert (
        await repository.cancel_reservation(
            identity,
            expected_generation=reservation.generation - 1,
            expected_session_id="1" * 32,
            expected_claim_token=reservation.claim_token,
        )
        is CandidateHealthSettlement.STALE
    )
    assert (
        await repository.expire_claim(
            identity,
            expected_generation=reservation.generation,
            expected_claim_kind=ModelCandidateClaimKind.RESERVATION,
            expected_owner_id="1" * 32,
            expected_claim_token=reservation.claim_token,
        )
        is CandidateHealthSettlement.STALE
    )

    await _expire_claim(rdb_session_manager, identity)
    assert (
        await repository.expire_claim(
            identity,
            expected_generation=reservation.generation,
            expected_claim_kind=ModelCandidateClaimKind.RESERVATION,
            expected_owner_id="1" * 32,
            expected_claim_token=reservation.claim_token,
        )
        is CandidateHealthSettlement.APPLIED
    )
    observation = await repository.snapshot(identity)
    assert observation.status is ModelCandidateHealthStatus.COOLDOWN
    assert observation.health is not None
    assert observation.health.claim_kind is None


async def test_in_session_transition_rolls_back_with_caller_transaction(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A composable transition has no independent commit boundary."""
    identity = await _fixture(rdb_session_manager, slug="candidate-health-rollback")
    repository = _repository(rdb_session_manager)

    async with rdb_session_manager() as session:
        renewed = await repository.renew_quota_in_session(session, identity)
        assert renewed.status is ModelCandidateHealthStatus.COOLDOWN
        assert renewed.health is not None
        await session.rollback()

    observation = await repository.snapshot(identity)
    assert observation.status is ModelCandidateHealthStatus.AVAILABLE
    assert observation.health is None
