"""Every finite health/probe outcome retains its selection and skip policy."""

import datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ModelCandidateClaimKind
from azents.core.model_operation import (
    ModelOperationCandidateOutcomeReason,
    ModelOperationCandidateOutcomeStatus,
    ModelOperationChainExhaustedError,
    ModelOperationKind,
)
from azents.repos.agent_execution.repository_test import _model_operation_state
from azents.repos.model_candidate_health import ModelCandidateHealthRepository
from azents.repos.model_candidate_health.data import (
    ForegroundProbeOutcome,
    ForegroundProbeResult,
    ModelCandidateHealthObservation,
    ModelCandidateHealthSnapshot,
    ModelCandidateHealthStatus,
    ModelCandidateIdentity,
)
from azents.repos.model_candidate_selection import select_model_operation_candidate

_NOW = datetime.datetime(2026, 10, 4, tzinfo=datetime.UTC)


@pytest.mark.parametrize("status", list(ModelCandidateHealthStatus))
async def test_complete_background_health_dispatch(
    status: ModelCandidateHealthStatus,
) -> None:
    operation = _model_operation_state().foreground
    assert operation is not None
    operation = operation.model_copy(
        update={"kind": ModelOperationKind.HISTORICAL_MEMORY}
    )
    health = AsyncMock(spec=ModelCandidateHealthRepository)
    health.snapshot_for_background_in_session.return_value = (
        ModelCandidateHealthObservation(server_time=_NOW, status=status, health=None)
    )
    if status is ModelCandidateHealthStatus.AVAILABLE:
        result = await select_model_operation_candidate(
            AsyncMock(spec=AsyncSession),
            operation=operation,
            workspace_id="workspace",
            health_repository=health,
            recorded_at=_NOW,
            session_id=None,
            reservation=None,
        )
        assert (
            result.operation.outcomes[0].status
            is ModelOperationCandidateOutcomeStatus.ACTIVE
        )
    else:
        with pytest.raises(ModelOperationChainExhaustedError) as failure:
            await select_model_operation_candidate(
                AsyncMock(spec=AsyncSession),
                operation=operation,
                workspace_id="workspace",
                health_repository=health,
                recorded_at=_NOW,
                session_id=None,
                reservation=None,
            )
        expected = (
            ModelOperationCandidateOutcomeReason.ACTIVE_COOLDOWN
            if status is ModelCandidateHealthStatus.COOLDOWN
            else ModelOperationCandidateOutcomeReason.BACKGROUND_PROBE_REQUIRED
        )
        assert failure.value.operation.outcomes[0].reason is expected
    health.claim_foreground_probe_in_session.assert_not_awaited()


@pytest.mark.parametrize("outcome", list(ForegroundProbeOutcome))
async def test_complete_foreground_probe_dispatch(
    outcome: ForegroundProbeOutcome,
) -> None:
    operation = _model_operation_state().foreground
    assert operation is not None
    selection = operation.current_candidate.model_selection
    snapshot = ModelCandidateHealthSnapshot(
        identity=ModelCandidateIdentity(
            workspace_id="workspace",
            llm_provider_integration_id=selection.llm_provider_integration_id,
            model_identifier=selection.model_identifier,
        ),
        generation=7,
        cooldown_until=_NOW,
        claim_kind=ModelCandidateClaimKind.PROBE,
        claim_owner_id=operation.operation_id,
        claim_token="p" * 32,
        claim_until=_NOW + datetime.timedelta(minutes=1),
        created_at=_NOW,
        updated_at=_NOW,
    )
    health = AsyncMock(spec=ModelCandidateHealthRepository)
    health.claim_foreground_probe_in_session.return_value = ForegroundProbeResult(
        outcome=outcome,
        observation=ModelCandidateHealthObservation(
            server_time=_NOW, status=ModelCandidateHealthStatus.CLAIMED, health=snapshot
        ),
    )
    if outcome in {ForegroundProbeOutcome.HEALTHY, ForegroundProbeOutcome.CLAIMED}:
        result = await select_model_operation_candidate(
            AsyncMock(spec=AsyncSession),
            operation=operation,
            workspace_id="workspace",
            health_repository=health,
            recorded_at=_NOW,
            session_id=None,
            reservation=None,
        )
        assert (
            result.operation.outcomes[0].status
            is ModelOperationCandidateOutcomeStatus.ACTIVE
        )
        assert result.reservation_consumed is False
        if outcome is ForegroundProbeOutcome.CLAIMED:
            claim = result.operation.transferred_probe_claim
            assert claim is not None
            assert claim.claim_token == snapshot.claim_token
            assert claim.health_generation == snapshot.generation
            assert claim.claim_owner_id == operation.operation_id
    else:
        with pytest.raises(ModelOperationChainExhaustedError) as failure:
            await select_model_operation_candidate(
                AsyncMock(spec=AsyncSession),
                operation=operation,
                workspace_id="workspace",
                health_repository=health,
                recorded_at=_NOW,
                session_id=None,
                reservation=None,
            )
        expected = (
            ModelOperationCandidateOutcomeReason.ACTIVE_COOLDOWN
            if outcome is ForegroundProbeOutcome.COOLDOWN
            else ModelOperationCandidateOutcomeReason.PROBE_CLAIM_BUSY
        )
        assert failure.value.operation.outcomes[0].reason is expected
    health.snapshot_for_background_in_session.assert_not_awaited()
