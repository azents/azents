"""Lightweight model snapshots and quota progression on the common AgentRun."""

import datetime
from dataclasses import dataclass

import sqlalchemy as sa
from uuid6 import uuid7

from azents.core.active_model_capabilities import (
    apply_to_options,
    compile_capture,
    identities_for_options,
    require_selection,
)
from azents.core.enums import AgentRunStatus, AgentSessionRunState, AgentSessionStatus
from azents.core.historical_memory_consolidation import (
    MemoryExecutionAuthorityError,
    MemoryExecutionBinding,
    MemoryExecutionPrincipal,
)
from azents.core.inference_profile import RequestedInferenceProfile
from azents.core.model_operation import (
    ModelOperationChainExhaustedError,
    ModelOperationKind,
    ModelOperationSnapshot,
    ModelOperationState,
    build_model_operation,
    mark_current_candidate_quota_and_advance,
)
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.engine.run.provider_failure import (
    ModelProviderFailure,
    ModelProviderFailureCategory,
)
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.historical_memory_execution import RDBMemoryExecution
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.active_model_capabilities import ActiveModelCapabilitiesRepository
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_execution.data import AgentRunPatch
from azents.repos.hierarchy_contention import retry_hierarchy_operation
from azents.repos.historical_memory_consolidation.execution import (
    MemoryExecutionRepository,
)
from azents.repos.model_candidate_health import ModelCandidateHealthRepository
from azents.repos.model_candidate_health.data import ModelCandidateIdentity
from azents.repos.model_candidate_selection import select_model_operation_candidate


@dataclass(frozen=True)
class ConsolidationModelOperationRepository:
    """Reuse common candidate selection, keeping only configured Lightweight intent."""

    session_manager: SessionManager[WriteSession]
    agent_repository: AgentRepository
    health_repository: ModelCandidateHealthRepository
    active_capabilities_repository: ActiveModelCapabilitiesRepository
    execution_repository: MemoryExecutionRepository
    run_repository: AgentRunRepository

    async def archivable_predecessors(
        self, binding: MemoryExecutionBinding
    ) -> tuple[SessionExecutionOwner, ...]:
        """Observe settled exact-unit predecessors without admitting abandonment."""
        async with self.session_manager() as session:
            active_run = sa.exists(
                sa.select(RDBAgentRun.id).where(
                    RDBAgentRun.session_id == RDBAgentSession.id,
                    RDBAgentRun.status.in_(
                        (AgentRunStatus.RUNNING, AgentRunStatus.PENDING)
                    ),
                )
            )
            rows = await session.read_session.execute(
                sa.select(RDBAgentSession.id, RDBAgentSession.owner_generation)
                .join(
                    RDBMemoryExecution,
                    RDBMemoryExecution.session_id == RDBAgentSession.id,
                )
                .where(
                    RDBMemoryExecution.unit_id == binding.unit_id,
                    RDBAgentSession.id != binding.session_id,
                    RDBAgentSession.workspace_id == binding.unit.workspace_id,
                    RDBAgentSession.agent_id == binding.unit.agent_id,
                    RDBAgentSession.lifecycle_root_session_id.is_(None),
                    RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                    RDBAgentSession.run_state == AgentSessionRunState.IDLE,
                    ~active_run,
                )
                .order_by(RDBAgentSession.id)
            )
            return tuple(SessionExecutionOwner(row[0], row[1]) for row in rows)

    @retry_hierarchy_operation
    async def begin(
        self, principal: MemoryExecutionPrincipal
    ) -> ModelOperationSnapshot:
        """Freeze supported candidates in the actual Run before provider setup."""
        selection_error: ModelOperationChainExhaustedError | None = None
        async with self.session_manager() as session:
            await self.execution_repository.authorize_in_session(session, principal)
            agent = await self.agent_repository.get_by_id(
                session, principal.binding.unit.agent_id
            )
            if (
                agent is None
                or agent.workspace_id != principal.binding.unit.workspace_id
            ):
                raise MemoryExecutionAuthorityError(
                    "Memory model scope is unavailable."
                )
            run = await self.run_repository.lock_by_id(session, principal.run_id)
            if run is None or run.session_id != principal.owner.session_id:
                raise MemoryExecutionAuthorityError("Memory model Run is unavailable.")
            state = run.model_operation_state or ModelOperationState(
                foreground=None, compaction=None
            )
            operation = state.foreground
            metadata = self.active_capabilities_repository
            captured = None
            compiled = None
            if operation is None:
                option = next(
                    (
                        item
                        for item in agent.selectable_model_options
                        if item.label == agent.lightweight_model_label
                    ),
                    None,
                )
                if option is None:
                    raise MemoryExecutionAuthorityError(
                        "Memory Lightweight option is unavailable."
                    )
                captured = await metadata.capture_exact_choices_in_session(
                    session,
                    workspace_id=agent.workspace_id,
                    identities=identities_for_options([option]),
                )
                compiled = compile_capture(
                    captured,
                    selections=[
                        candidate.model_selection for candidate in option.candidates
                    ],
                )
                option = apply_to_options([option], compiled)[0]
                operation = build_model_operation(
                    option=option,
                    profile=RequestedInferenceProfile(
                        model_target_label=option.label,
                        reasoning_effort=None,
                        enabled_execution_options=[],
                    ),
                    kind=ModelOperationKind.FOREGROUND,
                    operation_id=uuid7().hex,
                    recorded_at=datetime.datetime.now(datetime.UTC),
                )
            elif operation.kind is not ModelOperationKind.FOREGROUND:
                raise MemoryExecutionAuthorityError(
                    "Memory model snapshot is unavailable."
                )
            try:
                selected = await select_model_operation_candidate(
                    session,
                    operation=operation,
                    workspace_id=agent.workspace_id,
                    health_repository=self.health_repository,
                    recorded_at=datetime.datetime.now(datetime.UTC),
                    session_id=None,
                    reservation=None,
                )
                updated = selected.operation
                if compiled is not None:
                    require_selection(
                        compiled, updated.current_candidate.model_selection
                    )
            except ModelOperationChainExhaustedError as exhausted:
                updated = exhausted.operation
                selection_error = exhausted
            if captured is not None and not await metadata.inputs_match_in_session(
                session, captured=captured
            ):
                raise MemoryExecutionAuthorityError(
                    "Memory model metadata changed during setup."
                )
            await self.run_repository.update(
                session,
                principal.run_id,
                AgentRunPatch(
                    model_operation_state=ModelOperationState(
                        foreground=updated, compaction=state.compaction
                    )
                ),
            )
        if selection_error is not None:
            raise selection_error
        return updated

    @retry_hierarchy_operation
    async def replace_after_quota(
        self,
        principal: MemoryExecutionPrincipal,
        *,
        failure: ModelProviderFailure,
    ) -> MemoryExecutionBinding | None:
        """Advance the frozen policy into clean execution after exact provider quota."""
        if failure.category is not ModelProviderFailureCategory.QUOTA_OR_BILLING:
            raise ValueError("Only provider quota may advance the Memory model chain.")
        async with self.session_manager() as session:
            await self.execution_repository.authorize_in_session(session, principal)
            run = await self.run_repository.lock_by_id(session, principal.run_id)
            if run is None or run.model_operation_state is None:
                raise MemoryExecutionAuthorityError(
                    "Memory model snapshot is unavailable."
                )
            state = run.model_operation_state
            operation = state.foreground
            if operation is None or operation.kind is not ModelOperationKind.FOREGROUND:
                raise MemoryExecutionAuthorityError(
                    "Memory model snapshot is unavailable."
                )
            candidate = operation.current_candidate.model_selection
            if (
                failure.route_provider != candidate.provider.value
                or failure.route_model != candidate.model_identifier
                or failure.route_integration != candidate.llm_provider_integration_id
            ):
                raise MemoryExecutionAuthorityError(
                    "Memory quota route does not match."
                )
            observed = await self.health_repository.renew_quota_in_session(
                session,
                ModelCandidateIdentity(
                    workspace_id=principal.binding.unit.workspace_id,
                    llm_provider_integration_id=candidate.llm_provider_integration_id,
                    model_identifier=candidate.model_identifier,
                ),
            )
            try:
                advanced = mark_current_candidate_quota_and_advance(
                    operation, recorded_at=observed.server_time
                )
                selected = await select_model_operation_candidate(
                    session,
                    operation=advanced,
                    workspace_id=principal.binding.unit.workspace_id,
                    health_repository=self.health_repository,
                    recorded_at=observed.server_time,
                    session_id=None,
                    reservation=None,
                )
                updated = selected.operation
            except ModelOperationChainExhaustedError as exhausted:
                updated = exhausted.operation
            return await self.execution_repository.replace_after_quota_in_session(
                session, principal, updated
            )
