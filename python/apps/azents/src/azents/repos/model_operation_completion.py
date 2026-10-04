"""Database-only model-operation success composition."""

import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends

from azents.core.model_operation import (
    ModelOperationCandidateOutcomeStatus,
    ModelOperationKind,
    ModelOperationState,
    mark_model_operation_succeeded,
)
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_execution.data import AgentRunPatch
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.model_candidate_health import ModelCandidateHealthRepository
from azents.repos.model_candidate_health.data import ModelCandidateIdentity
from azents.repos.session_execution import (
    CanonicalExecutionOwnerGenerationStaleError,
)


@dataclasses.dataclass(frozen=True)
class ModelOperationCompletion:
    """Authority and operation identity required for successful settlement."""

    workspace_id: str
    session_id: str
    run_id: str
    owner_generation: int
    operation_kind: ModelOperationKind


@dataclasses.dataclass(frozen=True)
class ModelOperationCompletionRepository:
    """Settle one successful model operation inside a composing repository."""

    agent_session_repository: Annotated[
        AgentSessionRepository,
        Depends(AgentSessionRepository),
    ]
    agent_run_repository: Annotated[
        AgentRunRepository,
        Depends(AgentRunRepository),
    ]
    model_candidate_health_repository: Annotated[
        ModelCandidateHealthRepository,
        Depends(ModelCandidateHealthRepository),
    ]

    async def complete_success_in_session(
        self,
        session: WriteSession,
        completion: ModelOperationCompletion,
    ) -> None:
        """Settle operation success in the caller's database-only transaction."""
        current_session = (
            await self.agent_session_repository.wait_for_execution_lock_by_id(
                session,
                completion.session_id,
            )
        )
        if (
            current_session is None
            or current_session.owner_generation != completion.owner_generation
        ):
            raise CanonicalExecutionOwnerGenerationStaleError(
                "Session owner generation is stale"
            )

        locked_run = await self.agent_run_repository.lock_by_id(
            session,
            completion.run_id,
        )
        if locked_run is None or locked_run.model_operation_state is None:
            return
        state = locked_run.model_operation_state
        operation = (
            state.foreground
            if completion.operation_kind is ModelOperationKind.FOREGROUND
            else state.compaction
        )
        if operation is None or operation.terminal_reason is not None:
            return
        current_outcome = operation.outcomes[operation.cursor]
        if current_outcome.status is not ModelOperationCandidateOutcomeStatus.ACTIVE:
            return
        claim = operation.transferred_probe_claim
        if claim is not None:
            selection = operation.current_candidate.model_selection
            complete_probe = (
                self.model_candidate_health_repository.complete_probe_success_in_session
            )
            await complete_probe(
                session,
                ModelCandidateIdentity(
                    workspace_id=completion.workspace_id,
                    llm_provider_integration_id=(selection.llm_provider_integration_id),
                    model_identifier=selection.model_identifier,
                ),
                expected_generation=claim.health_generation,
                expected_owner_id=claim.claim_owner_id,
                expected_claim_token=claim.claim_token,
            )
        succeeded = mark_model_operation_succeeded(
            operation,
            recorded_at=datetime.datetime.now(datetime.UTC),
        )
        next_state = ModelOperationState(
            foreground=(
                succeeded
                if completion.operation_kind is ModelOperationKind.FOREGROUND
                else state.foreground
            ),
            compaction=(
                None
                if completion.operation_kind is ModelOperationKind.COMPACTION
                else state.compaction
            ),
        )
        await self.agent_run_repository.update(
            session,
            completion.run_id,
            AgentRunPatch(model_operation_state=next_state),
        )
