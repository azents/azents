"""Shared candidate compatibility and PostgreSQL health selection."""

import dataclasses
import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ModelCandidateClaimKind
from azents.core.model_availability import PrimaryModelReservation
from azents.core.model_execution_options import validate_execution_options
from azents.core.model_operation import (
    ModelOperationCandidateOutcomeReason,
    ModelOperationCandidateOutcomeStatus,
    ModelOperationCandidateSnapshot,
    ModelOperationKind,
    ModelOperationSnapshot,
    TransferredModelCandidateClaim,
    mark_current_candidate_active,
    mark_current_candidate_skipped_and_advance,
    set_transferred_probe_claim,
)
from azents.repos.model_candidate_health import ModelCandidateHealthRepository
from azents.repos.model_candidate_health.data import (
    ForegroundProbeOutcome,
    ModelCandidateHealthStatus,
    ModelCandidateIdentity,
)


@dataclasses.dataclass(frozen=True)
class ModelCandidateSelection:
    """Selected candidate and updated durable operation snapshot."""

    operation: ModelOperationSnapshot
    candidate: ModelOperationCandidateSnapshot
    reservation_consumed: bool


async def select_model_operation_candidate(
    session: AsyncSession,
    *,
    operation: ModelOperationSnapshot,
    workspace_id: str,
    health_repository: ModelCandidateHealthRepository,
    recorded_at: datetime.datetime,
    session_id: str | None,
    reservation: PrimaryModelReservation | None,
) -> ModelCandidateSelection:
    """Select and claim one compatible candidate inside a caller transaction."""
    current = operation
    while True:
        candidate = current.current_candidate
        outcome = current.outcomes[current.cursor]
        if outcome.status is ModelOperationCandidateOutcomeStatus.ACTIVE:
            return ModelCandidateSelection(
                operation=current,
                candidate=candidate,
                reservation_consumed=False,
            )
        incompatibility = _candidate_incompatibility(current, candidate)
        if incompatibility is not None:
            current = mark_current_candidate_skipped_and_advance(
                current,
                status=ModelOperationCandidateOutcomeStatus.INCOMPATIBLE,
                reason=incompatibility,
                recorded_at=recorded_at,
            )
            continue

        identity = _health_identity(workspace_id, candidate)
        transferred = await _transfer_primary_reservation(
            session,
            operation=current,
            identity=identity,
            health_repository=health_repository,
            session_id=session_id,
            reservation=reservation,
        )
        if transferred is not None:
            active = mark_current_candidate_active(
                current,
                reason=ModelOperationCandidateOutcomeReason.PRIMARY_RESERVATION,
                recorded_at=transferred.transferred_at,
            )
            return ModelCandidateSelection(
                operation=set_transferred_probe_claim(active, transferred),
                candidate=candidate,
                reservation_consumed=True,
            )

        if current.kind is not ModelOperationKind.FOREGROUND:
            observation = await health_repository.snapshot_for_background_in_session(
                session,
                identity,
            )
            if observation.status is ModelCandidateHealthStatus.AVAILABLE:
                active = mark_current_candidate_active(
                    current,
                    reason=ModelOperationCandidateOutcomeReason.SELECTED,
                    recorded_at=observation.server_time,
                )
                return ModelCandidateSelection(
                    operation=active,
                    candidate=candidate,
                    reservation_consumed=False,
                )
            if observation.status is ModelCandidateHealthStatus.COOLDOWN:
                status = ModelOperationCandidateOutcomeStatus.COOLDOWN
                reason = ModelOperationCandidateOutcomeReason.ACTIVE_COOLDOWN
            else:
                status = ModelOperationCandidateOutcomeStatus.PROBE_BUSY
                reason = ModelOperationCandidateOutcomeReason.BACKGROUND_PROBE_REQUIRED
            current = mark_current_candidate_skipped_and_advance(
                current,
                status=status,
                reason=reason,
                recorded_at=observation.server_time,
            )
            continue

        probe = await health_repository.claim_foreground_probe_in_session(
            session,
            identity,
            owner_id=current.operation_id,
        )
        if probe.outcome is ForegroundProbeOutcome.HEALTHY:
            active = mark_current_candidate_active(
                current,
                reason=ModelOperationCandidateOutcomeReason.SELECTED,
                recorded_at=probe.observation.server_time,
            )
            return ModelCandidateSelection(
                operation=active,
                candidate=candidate,
                reservation_consumed=False,
            )
        if probe.outcome is ForegroundProbeOutcome.CLAIMED:
            health = probe.observation.health
            if (
                health is None
                or health.claim_token is None
                or health.claim_until is None
            ):
                raise RuntimeError("Foreground probe claim returned incomplete state")
            active = mark_current_candidate_active(
                current,
                reason=ModelOperationCandidateOutcomeReason.HALF_OPEN_PROBE,
                recorded_at=probe.observation.server_time,
            )
            claim = TransferredModelCandidateClaim(
                kind=ModelCandidateClaimKind.PROBE,
                candidate_ordinal=candidate.ordinal,
                health_generation=health.generation,
                claim_owner_id=current.operation_id,
                claim_token=health.claim_token,
                claim_until=health.claim_until,
                transferred_at=probe.observation.server_time,
            )
            return ModelCandidateSelection(
                operation=set_transferred_probe_claim(active, claim),
                candidate=candidate,
                reservation_consumed=False,
            )
        if probe.outcome is ForegroundProbeOutcome.COOLDOWN:
            status = ModelOperationCandidateOutcomeStatus.COOLDOWN
            reason = ModelOperationCandidateOutcomeReason.ACTIVE_COOLDOWN
        else:
            status = ModelOperationCandidateOutcomeStatus.PROBE_BUSY
            reason = ModelOperationCandidateOutcomeReason.PROBE_CLAIM_BUSY
        current = mark_current_candidate_skipped_and_advance(
            current,
            status=status,
            reason=reason,
            recorded_at=probe.observation.server_time,
        )


async def _transfer_primary_reservation(
    session: AsyncSession,
    *,
    operation: ModelOperationSnapshot,
    identity: ModelCandidateIdentity,
    health_repository: ModelCandidateHealthRepository,
    session_id: str | None,
    reservation: PrimaryModelReservation | None,
) -> TransferredModelCandidateClaim | None:
    if (
        operation.kind is not ModelOperationKind.FOREGROUND
        or operation.cursor != 0
        or session_id is None
        or reservation is None
        or reservation.semantic_label != operation.semantic_label
        or reservation.candidate.llm_provider_integration_id
        != identity.llm_provider_integration_id
        or reservation.candidate.model_identifier != identity.model_identifier
    ):
        return None
    transferred = await health_repository.transfer_reservation_in_session(
        session,
        identity,
        expected_generation=reservation.health_generation,
        expected_session_id=session_id,
        expected_claim_token=reservation.claim_token,
        operation_id=operation.operation_id,
    )
    if transferred is None:
        return None
    health = transferred.health
    if health.claim_token is None or health.claim_until is None:
        raise RuntimeError("Transferred reservation returned incomplete state")
    return TransferredModelCandidateClaim(
        kind=ModelCandidateClaimKind.PROBE,
        candidate_ordinal=1,
        health_generation=health.generation,
        claim_owner_id=operation.operation_id,
        claim_token=health.claim_token,
        claim_until=health.claim_until,
        transferred_at=transferred.server_time,
    )


def _candidate_incompatibility(
    operation: ModelOperationSnapshot,
    candidate: ModelOperationCandidateSnapshot,
) -> ModelOperationCandidateOutcomeReason | None:
    selection = candidate.model_selection
    requested_effort = operation.requested_reasoning_effort
    if (
        requested_effort is not None
        and requested_effort
        not in selection.normalized_capabilities.reasoning.effort_levels
    ):
        return ModelOperationCandidateOutcomeReason.REASONING_EFFORT_UNSUPPORTED
    try:
        validate_execution_options(
            provider=selection.provider,
            supported=selection.supported_execution_options,
            enabled=operation.requested_execution_options,
        )
    except ValueError:
        return ModelOperationCandidateOutcomeReason.EXECUTION_OPTION_UNSUPPORTED
    return None


def _health_identity(
    workspace_id: str,
    candidate: ModelOperationCandidateSnapshot,
) -> ModelCandidateIdentity:
    selection = candidate.model_selection
    return ModelCandidateIdentity(
        workspace_id=workspace_id,
        llm_provider_integration_id=selection.llm_provider_integration_id,
        model_identifier=selection.model_identifier,
    )
