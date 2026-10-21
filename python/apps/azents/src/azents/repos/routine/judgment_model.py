"""Current label resolution and shared background-candidate policy for Judge calls."""

import datetime
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from azents.core.active_model_capabilities import (
    CompiledActiveChoices,
    apply_to_options,
    compile_capture,
    identities_for_options,
    require_selection,
)
from azents.core.inference_profile import RequestedInferenceProfile
from azents.core.model_operation import (
    ModelOperationChainExhaustedError,
    ModelOperationKind,
    ModelOperationSnapshot,
    build_model_operation,
    mark_current_candidate_quota_and_advance,
)
from azents.core.routine import RoutineScope
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.active_model_capabilities import ActiveModelCapabilitiesRepository
from azents.repos.agent import AgentRepository
from azents.repos.model_candidate_health import ModelCandidateHealthRepository
from azents.repos.model_candidate_health.data import ModelCandidateIdentity
from azents.repos.model_candidate_selection import select_model_operation_candidate
from azents.repos.routine.scope import fence_routine_scope


@dataclass(frozen=True)
class RoutineJudgmentModelState:
    """One call-local chain; the durable action retains only its semantic input."""

    operation: ModelOperationSnapshot
    compiled: CompiledActiveChoices


@dataclass(frozen=True)
class RoutineJudgmentModelRepository:
    """Use ordinary Session fencing without touching foreground operation slots."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    agents: Annotated[AgentRepository, Depends(AgentRepository)]
    active_capabilities: Annotated[
        ActiveModelCapabilitiesRepository, Depends(ActiveModelCapabilitiesRepository)
    ]
    health: Annotated[
        ModelCandidateHealthRepository, Depends(ModelCandidateHealthRepository)
    ]

    async def prepare(
        self,
        *,
        scope: RoutineScope,
        owner: SessionExecutionOwner,
        profile: RequestedInferenceProfile,
        operation_id: str,
    ) -> RoutineJudgmentModelState | None:
        """Read the current label and complete current local candidate evidence."""
        async with self.session_manager() as session:
            await fence_routine_scope(session, scope=scope, owner=owner)
            agent = await self.agents.get_by_id(session, scope.agent_id)
            if agent is None or not agent.enabled:
                return None
            option = next(
                (
                    item
                    for item in agent.selectable_model_options
                    if item.label == profile.model_target_label
                ),
                None,
            )
            if option is None:
                return None
            captured = await self.active_capabilities.capture_exact_choices_in_session(
                session,
                workspace_id=scope.workspace_id,
                identities=identities_for_options((option,)),
            )
        compiled = compile_capture(
            captured, selections=[item.model_selection for item in option.candidates]
        )
        active = apply_to_options((option,), compiled)[0]
        operation = build_model_operation(
            option=active,
            profile=profile,
            kind=ModelOperationKind.ROUTINE_JUDGMENT,
            operation_id=operation_id,
            recorded_at=datetime.datetime.now(datetime.UTC),
        )
        async with self.session_manager() as session:
            await fence_routine_scope(session, scope=scope, owner=owner)
            if not await self.active_capabilities.inputs_match_in_session(
                session, captured=captured
            ):
                return None
            return await self._select(
                session, scope=scope, operation=operation, compiled=compiled
            )

    async def advance_after_quota(
        self,
        *,
        scope: RoutineScope,
        owner: SessionExecutionOwner,
        current: RoutineJudgmentModelState,
    ) -> RoutineJudgmentModelState | None:
        """Record shared quota cooldown and use the common background selector."""
        selection = current.operation.current_candidate.model_selection
        async with self.session_manager() as session:
            await fence_routine_scope(session, scope=scope, owner=owner)
            observation = await self.health.renew_quota_in_session(
                session,
                ModelCandidateIdentity(
                    workspace_id=scope.workspace_id,
                    llm_provider_integration_id=selection.llm_provider_integration_id,
                    model_identifier=selection.model_identifier,
                ),
            )
            try:
                advanced = mark_current_candidate_quota_and_advance(
                    current.operation, recorded_at=observation.server_time
                )
            except ModelOperationChainExhaustedError:
                return None
            return await self._select(
                session, scope=scope, operation=advanced, compiled=current.compiled
            )

    async def _select(
        self,
        session: WriteSession,
        *,
        scope: RoutineScope,
        operation: ModelOperationSnapshot,
        compiled: CompiledActiveChoices,
    ) -> RoutineJudgmentModelState | None:
        try:
            selected = await select_model_operation_candidate(
                session,
                workspace_id=scope.workspace_id,
                operation=operation,
                health_repository=self.health,
                recorded_at=datetime.datetime.now(datetime.UTC),
                session_id=scope.session_id,
                reservation=None,
            )
        except ModelOperationChainExhaustedError:
            return None
        require_selection(compiled, selected.candidate.model_selection)
        return RoutineJudgmentModelState(selected.operation, compiled)
