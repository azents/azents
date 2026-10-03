"""Internal Lightweight route snapshots and quota-only shared candidate progression."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from azents.core.historical_memory_consolidation import ConsolidationJobPrincipal
from azents.core.inference_profile import RequestedInferenceProfile
from azents.core.model_operation import (
    ModelOperationCandidateOutcomeStatus,
    ModelOperationChainExhaustedError,
    ModelOperationKind,
    ModelOperationSnapshot,
    build_model_operation,
    mark_current_candidate_quota_and_advance,
    mark_model_operation_succeeded,
)
from azents.engine.run.provider_failure import (
    ModelProviderFailure,
    ModelProviderFailureCategory,
)
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.historical_memory_consolidation.authority import (
    ConsolidationAuthorityError,
    LockedConsolidationOwner,
    consolidation_job_session,
    require_commit_owner,
)
from azents.repos.historical_memory_consolidation.budget import check_input_influence
from azents.repos.model_candidate_health import ModelCandidateHealthRepository
from azents.repos.model_candidate_health.data import ModelCandidateIdentity
from azents.services.model_candidate_selection import select_model_operation_candidate


async def finish_consolidation_model_operation(
    session: AsyncSession,
    *,
    owner: LockedConsolidationOwner,
    health_repository: ModelCandidateHealthRepository,
) -> None:
    """Settle the internal operation in the same validated publication transaction."""
    if owner.attempt.model_operation_state is None:
        return
    operation = ModelOperationSnapshot.model_validate(
        owner.attempt.model_operation_state
    )
    if operation.terminal_reason is not None:
        raise ConsolidationAuthorityError("Consolidation model operation is exhausted.")
    if (
        operation.outcomes[operation.cursor].status
        is not ModelOperationCandidateOutcomeStatus.ACTIVE
    ):
        raise ConsolidationAuthorityError(
            "Consolidation model operation is not active."
        )
    claim = operation.transferred_probe_claim
    if claim is not None:
        selection = operation.current_candidate.model_selection
        await health_repository.complete_probe_success_in_session(
            session,
            ModelCandidateIdentity(
                workspace_id=owner.unit.workspace_id,
                llm_provider_integration_id=selection.llm_provider_integration_id,
                model_identifier=selection.model_identifier,
            ),
            expected_generation=claim.health_generation,
            expected_owner_id=claim.claim_owner_id,
            expected_claim_token=claim.claim_token,
        )
    succeeded = mark_model_operation_succeeded(
        operation, recorded_at=owner.database_now
    )
    owner.attempt.model_operation_state = succeeded.model_dump(mode="json")


@dataclass(frozen=True)
class ConsolidationModelOperationRepository:
    """Use existing Lightweight settings/health without a fabricated Session or Main."""

    session_manager: SessionManager[AsyncSession]
    agent_repository: AgentRepository
    health_repository: ModelCandidateHealthRepository

    async def begin(
        self, principal: ConsolidationJobPrincipal
    ) -> ModelOperationSnapshot:
        selection_error: ModelOperationChainExhaustedError | None = None
        async with consolidation_job_session(self.session_manager, principal) as job:
            session, owner = job.session, job.owner
            await check_input_influence(session, principal, owner)
            # Eligibility already holds a shared Agent lock. Read its typed
            # configuration without upgrading that lock while owning the unit.
            agent = await self.agent_repository.get_by_id(
                session, principal.unit.agent_id
            )
            if (
                agent is None
                or agent.workspace_id != principal.unit.workspace_id
                or not agent.memory_enabled
            ):
                raise ConsolidationAuthorityError(
                    "Consolidation model scope is unavailable."
                )
            option = next(
                (
                    option
                    for option in agent.selectable_model_options
                    if option.label == agent.lightweight_model_label
                ),
                None,
            )
            if option is None:
                raise ConsolidationAuthorityError(
                    "Consolidation Lightweight option is unavailable."
                )
            operation = (
                None
                if owner.attempt.model_operation_state is None
                else ModelOperationSnapshot.model_validate(
                    owner.attempt.model_operation_state
                )
            )
            if operation is None:
                operation = build_model_operation(
                    option=option,
                    profile=RequestedInferenceProfile(
                        model_target_label=option.label,
                        reasoning_effort=None,
                        enabled_execution_options=[],
                    ),
                    kind=ModelOperationKind.HISTORICAL_MEMORY,
                    operation_id=uuid7().hex,
                    recorded_at=owner.database_now,
                )
            elif (
                operation.kind is not ModelOperationKind.HISTORICAL_MEMORY
                or operation.semantic_label != option.label
            ):
                raise ConsolidationAuthorityError(
                    "Consolidation candidate snapshot is unavailable."
                )
            try:
                selected = await select_model_operation_candidate(
                    session,
                    operation=operation,
                    workspace_id=agent.workspace_id,
                    health_repository=self.health_repository,
                    recorded_at=owner.database_now,
                    session_id=None,
                    reservation=None,
                )
                updated = selected.operation
            except ModelOperationChainExhaustedError as exhausted:
                updated = exhausted.operation
                selection_error = exhausted
            owner.attempt.model_operation_state = updated.model_dump(mode="json")
            await require_commit_owner(session, owner)
        if selection_error is not None:
            raise selection_error
        return updated

    async def advance_after_quota(
        self,
        principal: ConsolidationJobPrincipal,
        *,
        failure: ModelProviderFailure,
    ) -> ModelOperationSnapshot | None:
        if failure.category is not ModelProviderFailureCategory.QUOTA_OR_BILLING:
            raise ValueError("Only provider quota may advance the consolidation chain.")
        async with consolidation_job_session(self.session_manager, principal) as job:
            session, owner = job.session, job.owner
            if owner.attempt.model_operation_state is None:
                raise ConsolidationAuthorityError(
                    "Consolidation candidate snapshot is unavailable."
                )
            operation = ModelOperationSnapshot.model_validate(
                owner.attempt.model_operation_state
            )
            candidate = operation.current_candidate.model_selection
            if (
                failure.route_provider != candidate.provider.value
                or failure.route_model != candidate.model_identifier
                or failure.route_integration != candidate.llm_provider_integration_id
            ):
                raise ConsolidationAuthorityError(
                    "Consolidation quota route does not match."
                )
            observation = await self.health_repository.renew_quota_in_session(
                session,
                ModelCandidateIdentity(
                    workspace_id=principal.unit.workspace_id,
                    llm_provider_integration_id=candidate.llm_provider_integration_id,
                    model_identifier=candidate.model_identifier,
                ),
            )
            try:
                advanced = mark_current_candidate_quota_and_advance(
                    operation, recorded_at=observation.server_time
                )
                selected = await select_model_operation_candidate(
                    session,
                    operation=advanced,
                    workspace_id=principal.unit.workspace_id,
                    health_repository=self.health_repository,
                    recorded_at=observation.server_time,
                    session_id=None,
                    reservation=None,
                )
                updated = selected.operation
                result = updated
            except ModelOperationChainExhaustedError as exhausted:
                updated = exhausted.operation
                result = None
            owner.attempt.model_operation_state = updated.model_dump(mode="json")
            await require_commit_owner(session, owner)
        return result
