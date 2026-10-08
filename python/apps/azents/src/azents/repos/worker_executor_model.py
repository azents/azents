"""Completed Worker model profile, quota and preparation atomic operations."""

import dataclasses
import datetime
from typing import Annotated

from azcommon.result import Failure, Result, Success
from azcommon.uuid import uuid7
from fastapi import Depends

from azents.core.active_model_capabilities import (
    apply_to_options,
    compile_capture,
    identities_for_options,
    require_selection,
)
from azents.core.agent_session_data import AgentSession
from azents.core.inference_profile import (
    InferenceProfileSource,
    RequestedInferenceProfile,
    SessionInferenceState,
)
from azents.core.model_operation import (
    ModelOperationChainExhaustedError,
    ModelOperationKind,
    ModelOperationSnapshot,
    ModelOperationState,
    build_model_operation,
    mark_current_candidate_quota_and_advance,
)
from azents.core.worker_model_profile import (
    ModelCandidateChainExhausted,
    ModelQuotaAdvanceResult,
    ModelTargetNotFound,
    ProfileResolutionRuntimeError,
    RequestedProfileSelection,
    agent_default_inference_profile,
    normalize_profile_selection_for_agent,
    profile_resolution_failure,
)
from azents.engine.run.provider_failure import ModelProviderFailure
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.active_model_capabilities import ActiveModelCapabilitiesRepository
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_execution.data import AgentRunPatch
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.model_candidate_health import ModelCandidateHealthRepository
from azents.repos.model_candidate_health.data import ModelCandidateIdentity
from azents.repos.model_candidate_selection import (
    ModelCandidateSelection,
    select_model_operation_candidate,
)
from azents.repos.session_execution import CanonicalExecutionOwnerGenerationStaleError
from azents.repos.worker_executor_model_data import (
    FreshModelPreparation,
    FreshProfileSnapshot,
    agent_model_configuration_signature,
    apply_frozen_operation,
    run_model_intent_signature,
)
from azents.repos.worker_session import WorkerSessionOperationRepository
from azents.repos.worker_session_data import CanonicalExecutionWorkDriftError


def _requested_profile(
    agent: Agent,
    session: AgentSession,
    override: RequestedProfileSelection | None,
) -> RequestedProfileSelection:
    """Keep raw input separate from metadata-dependent fallback normalization."""
    if override is not None and override.source in {
        InferenceProfileSource.PARENT_RUN,
        InferenceProfileSource.SPAWN_OVERRIDE,
        InferenceProfileSource.RETRY_ORIGINAL,
    }:
        return override
    if session.applied_inference_profile is not None:
        applied = session.applied_inference_profile
        return RequestedProfileSelection(
            RequestedInferenceProfile(
                model_target_label=applied.model_target_label,
                reasoning_effort=applied.reasoning_effort,
                enabled_execution_options=applied.enabled_execution_options,
            ),
            InferenceProfileSource.SESSION_LAST_USED,
        )
    return RequestedProfileSelection(
        agent_default_inference_profile(agent), InferenceProfileSource.AGENT_DEFAULT
    )


def _reuses_foreground(
    operation: ModelOperationSnapshot | None,
    profile: RequestedInferenceProfile,
    *,
    replace_operation: bool,
) -> bool:
    return (
        not replace_operation
        and operation is not None
        and operation.terminal_reason is None
        and operation.semantic_label == profile.model_target_label
        and operation.requested_reasoning_effort == profile.reasoning_effort
        and operation.requested_execution_options == profile.enabled_execution_options
    )


@dataclasses.dataclass(frozen=True)
class WorkerExecutorModelOperationRepository:
    """Own the six existing Worker database groups without external callbacks."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    agent_run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)]
    model_candidate_health_repository: Annotated[
        ModelCandidateHealthRepository, Depends(ModelCandidateHealthRepository)
    ]
    worker_session_repository: Annotated[
        WorkerSessionOperationRepository, Depends(WorkerSessionOperationRepository)
    ]
    active_capabilities_repository: Annotated[
        ActiveModelCapabilitiesRepository, Depends(ActiveModelCapabilitiesRepository)
    ]

    async def select_requested_profile(
        self,
        *,
        agent_id: str,
        session_id: str,
        explicit_profile: RequestedInferenceProfile | None,
        run_id: str | None = None,
    ) -> RequestedProfileSelection:
        """Apply explicit, Session-applied, then Agent-default profile precedence."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if not isinstance(agent, Agent):
                raise ValueError("Agent not found")
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            if not isinstance(agent_session, AgentSession):
                raise ValueError("AgentSession not found")
            if agent_session.agent_id != agent_id:
                raise ValueError("AgentSession does not belong to Agent")

            if explicit_profile is not None:
                selected = RequestedProfileSelection(
                    profile=explicit_profile,
                    source=InferenceProfileSource.EXPLICIT_INPUT,
                )
            elif agent_session.applied_inference_profile is not None:
                applied = agent_session.applied_inference_profile
                selected = RequestedProfileSelection(
                    profile=RequestedInferenceProfile(
                        model_target_label=applied.model_target_label,
                        reasoning_effort=applied.reasoning_effort,
                        enabled_execution_options=applied.enabled_execution_options,
                    ),
                    source=InferenceProfileSource.SESSION_LAST_USED,
                )
            else:
                selected = RequestedProfileSelection(
                    profile=agent_default_inference_profile(agent),
                    source=InferenceProfileSource.AGENT_DEFAULT,
                )

            run = (
                await self.agent_run_repository.get_by_id(session, run_id)
                if run_id is not None
                else None
            )
            if run is not None and run.session_id != session_id:
                raise ValueError("AgentRun does not belong to AgentSession")
            foreground = (
                run.model_operation_state.foreground
                if run is not None and run.model_operation_state is not None
                else None
            )
            reused = _reuses_foreground(
                foreground, selected.profile, replace_operation=False
            )
            capture_exact = (
                self.active_capabilities_repository.capture_exact_choices_in_session
            )
            captured = (
                await capture_exact(
                    session,
                    workspace_id=agent.workspace_id,
                    identities=identities_for_options(agent.selectable_model_options),
                )
                if not reused
                else None
            )
        compiled = (
            compile_capture(
                captured,
                selections=[
                    candidate.model_selection
                    for option in agent.selectable_model_options
                    for candidate in option.candidates
                ],
            )
            if captured is not None
            else None
        )
        options = (
            apply_to_options(agent.selectable_model_options, compiled)
            if compiled is not None
            else apply_frozen_operation(agent.selectable_model_options, foreground)
        )
        active_agent = agent.model_copy(update={"selectable_model_options": options})
        return normalize_profile_selection_for_agent(active_agent, selected)

    async def advance_after_quota(
        self,
        *,
        session_id: str,
        run_id: str,
        owner_generation: int,
        workspace_id: str,
        failure: ModelProviderFailure,
    ) -> ModelQuotaAdvanceResult:
        """Renew candidate health and advance before the generic retry budget."""
        if failure.operation == "sampling":
            operation_kind = ModelOperationKind.FOREGROUND
        elif failure.operation == "compaction":
            operation_kind = ModelOperationKind.COMPACTION
        else:
            raise ValueError("Run quota transition received an unsupported operation")

        async with self.session_manager() as session:
            await self.worker_session_repository.assert_owner_generation_in_session(
                session,
                session_id=session_id,
                owner_generation=owner_generation,
            )
            locked_session = await self.agent_session_repository.lock_by_id(
                session,
                session_id,
            )
            locked_run = await self.agent_run_repository.lock_by_id(
                session,
                run_id,
            )
            if locked_session is None or locked_run is None:
                raise ValueError("AgentSession or AgentRun not found")
            state = locked_run.model_operation_state
            if state is None:
                raise CanonicalExecutionWorkDriftError(
                    "Quota failure has no durable model operation"
                )
            operation = (
                state.foreground
                if operation_kind is ModelOperationKind.FOREGROUND
                else state.compaction
            )
            if operation is None:
                raise CanonicalExecutionWorkDriftError(
                    "Quota failure has no matching model operation slot"
                )
            candidate = operation.current_candidate
            selection = candidate.model_selection
            runtime_model = selection.model_identifier
            if (
                failure.route_integration != selection.llm_provider_integration_id
                or failure.route_provider != selection.provider.value
                or failure.route_model != runtime_model
            ):
                raise CanonicalExecutionWorkDriftError(
                    "Quota failure does not match the active model candidate"
                )
            identity = ModelCandidateIdentity(
                workspace_id=workspace_id,
                llm_provider_integration_id=(selection.llm_provider_integration_id),
                model_identifier=selection.model_identifier,
            )
            claim = operation.transferred_probe_claim
            if claim is None:
                observation = (
                    await self.model_candidate_health_repository.renew_quota_in_session(
                        session,
                        identity,
                    )
                )
            else:
                health_repository = self.model_candidate_health_repository
                renew_claimed_quota = health_repository.renew_claimed_quota_in_session
                (
                    _,
                    observation,
                ) = await renew_claimed_quota(
                    session,
                    identity,
                    expected_generation=claim.health_generation,
                    expected_claim_kind=claim.kind,
                    expected_owner_id=claim.claim_owner_id,
                    expected_claim_token=claim.claim_token,
                )
            exhausted = False
            try:
                advanced = mark_current_candidate_quota_and_advance(
                    operation,
                    recorded_at=observation.server_time,
                )
                selected = await select_model_operation_candidate(
                    session,
                    operation=advanced,
                    workspace_id=workspace_id,
                    health_repository=self.model_candidate_health_repository,
                    recorded_at=observation.server_time,
                    session_id=(
                        session_id
                        if operation_kind is ModelOperationKind.FOREGROUND
                        else None
                    ),
                    reservation=(
                        locked_session.primary_model_reservation
                        if operation_kind is ModelOperationKind.FOREGROUND
                        else None
                    ),
                )
                resulting_operation = selected.operation
                if selected.reservation_consumed:
                    reservation = locked_session.primary_model_reservation
                    if reservation is None:
                        raise CanonicalExecutionWorkDriftError(
                            "Transferred reservation disappeared"
                        )
                    set_reservation = (
                        self.agent_session_repository.set_primary_model_reservation
                    )
                    cleared = await set_reservation(
                        session,
                        session_id=session_id,
                        reservation=None,
                        expected_reservation_generation=(
                            reservation.reservation_generation
                        ),
                    )
                    if cleared is None:
                        raise CanonicalExecutionWorkDriftError(
                            "Transferred reservation changed"
                        )
            except ModelOperationChainExhaustedError as exc:
                resulting_operation = exc.operation
                exhausted = True
            next_state = ModelOperationState(
                foreground=(
                    resulting_operation
                    if operation_kind is ModelOperationKind.FOREGROUND
                    else state.foreground
                ),
                compaction=(
                    resulting_operation
                    if operation_kind is ModelOperationKind.COMPACTION
                    else state.compaction
                ),
            )
            await self.agent_run_repository.update(
                session,
                run_id,
                AgentRunPatch(
                    model_operation_state=next_state,
                    retry_state=None,
                    model_call_started_at=None,
                ),
            )
        return ModelQuotaAdvanceResult(
            operation=resulting_operation,
            exhausted=exhausted,
        )

    async def load_fresh_profile_snapshot(
        self,
        *,
        agent_id: str,
        session_id: str,
        run_id: str | None = None,
        override: RequestedProfileSelection | None = None,
        replace_operation: bool = False,
        include_foreground: bool = True,
    ) -> FreshProfileSnapshot:
        """Capture NEW slots before normalization; reused slots never read metadata."""
        async with self.session_manager() as session:
            session_state = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            agent = await self.agent_repository.get_by_id(session, agent_id)
            run = (
                await self.agent_run_repository.get_by_id(session, run_id)
                if run_id is not None
                else None
            )
            if session_state is None or agent is None:
                raise ValueError("AgentSession or Agent not found")
            if run_id is not None and run is None:
                raise ValueError("AgentRun not found")
            if session_state.agent_id != agent_id:
                raise ValueError("AgentSession does not belong to Agent")
            if run is not None and run.session_id != session_id:
                raise ValueError("AgentRun does not belong to AgentSession")
            state = run.model_operation_state if run is not None else None
            foreground = state.foreground if state is not None else None
            compaction = state.compaction if state is not None else None
            raw_profile = _requested_profile(agent, session_state, override).profile
            target_configured = any(
                option.label == raw_profile.model_target_label
                for option in agent.selectable_model_options
            )
            reused_foreground = not include_foreground or (
                target_configured
                and _reuses_foreground(
                    foreground, raw_profile, replace_operation=replace_operation
                )
            )
            target = (
                raw_profile.model_target_label
                if any(
                    option.label == raw_profile.model_target_label
                    for option in agent.selectable_model_options
                )
                else agent_default_inference_profile(agent).model_target_label
            )
            new_labels = set()
            if not reused_foreground:
                new_labels.add(target)
            if compaction is None or compaction.terminal_reason is not None:
                new_labels.add(agent.lightweight_model_label)
            new_options = [
                option
                for option in agent.selectable_model_options
                if option.label in new_labels
            ]
            capture_exact = (
                self.active_capabilities_repository.capture_exact_choices_in_session
            )
            captured = (
                await capture_exact(
                    session,
                    workspace_id=agent.workspace_id,
                    identities=identities_for_options(new_options),
                )
                if new_options
                else None
            )
        compiled = (
            compile_capture(
                captured,
                selections=[
                    candidate.model_selection
                    for option in new_options
                    for candidate in option.candidates
                ],
            )
            if captured is not None
            else None
        )
        active_options = (
            apply_to_options(agent.selectable_model_options, compiled)
            if compiled is not None
            else agent.selectable_model_options
        )
        compaction_option = next(
            (
                option
                for option in active_options
                if option.label == agent.lightweight_model_label
            ),
            None,
        )
        if compaction is not None and compaction.terminal_reason is None:
            # A reused background operation is independent of current label mapping.
            compaction_option = next(
                (
                    option
                    for option in apply_frozen_operation(active_options, compaction)
                    if option.label == compaction.semantic_label
                ),
                compaction_option,
            )
        if reused_foreground:
            active_options = apply_frozen_operation(active_options, foreground)
        return FreshProfileSnapshot(
            agent=agent.model_copy(update={"selectable_model_options": active_options}),
            session=session_state,
            raw_configuration_signature=agent_model_configuration_signature(agent),
            raw_run_intent_signature=run_model_intent_signature(run),
            operation_state=state,
            captured_inputs=captured,
            compiled_choices=compiled,
            compaction_option=compaction_option,
        )

    async def prepare_fresh(
        self,
        *,
        agent_id: str,
        session_id: str,
        run_id: str,
        owner_generation: int,
        selected: RequestedProfileSelection,
        override: RequestedProfileSelection | None,
        replace_operation: bool,
        prepared_snapshot: FreshProfileSnapshot | None = None,
    ) -> Result[
        FreshModelPreparation | None,
        ModelTargetNotFound | ModelCandidateChainExhausted,
    ]:
        """Commit reached normal failures, or return None for prewrite drift."""
        override_sources = {
            InferenceProfileSource.PARENT_RUN,
            InferenceProfileSource.SPAWN_OVERRIDE,
            InferenceProfileSource.RETRY_ORIGINAL,
        }
        frame = prepared_snapshot
        if frame is None:
            frame = await self.load_fresh_profile_snapshot(
                agent_id=agent_id,
                session_id=session_id,
                run_id=run_id,
                override=override,
                replace_operation=replace_operation,
            )
        async with self.session_manager() as session:
            locked_agent = await self.agent_repository.lock_by_id(
                session,
                agent_id,
            )
            locked_session = await self.agent_session_repository.lock_by_id(
                session,
                session_id,
            )
            locked_run = await self.agent_run_repository.lock_by_id(
                session,
                run_id,
            )
            if locked_agent is None or locked_session is None or locked_run is None:
                raise ValueError("AgentSession, Agent, or AgentRun not found")
            if locked_session.owner_generation != owner_generation:
                raise CanonicalExecutionOwnerGenerationStaleError(
                    "Session owner generation is stale"
                )
            if locked_session.agent_id != agent_id:
                raise ValueError("AgentSession does not belong to Agent")
            if locked_run.session_id != session_id:
                raise ValueError("AgentRun does not belong to AgentSession")

            if (
                agent_model_configuration_signature(locked_agent)
                != frame.raw_configuration_signature
                or locked_session.applied_inference_profile
                != frame.session.applied_inference_profile
                or locked_session.applied_profile_generation
                != frame.session.applied_profile_generation
                or run_model_intent_signature(locked_run)
                != frame.raw_run_intent_signature
                or locked_run.model_operation_state != frame.operation_state
            ):
                return Success(None)
            inputs_match = self.active_capabilities_repository.inputs_match_in_session
            if frame.captured_inputs is not None and not await inputs_match(
                session, captured=frame.captured_inputs
            ):
                return Success(None)
            active_agent = frame.agent
            stale_profile_was_replaced = False
            if override is not None and override.source in override_sources:
                expected_selection = normalize_profile_selection_for_agent(
                    active_agent,
                    override,
                )
                expected = expected_selection.profile
                stale_profile_was_replaced = expected != override.profile
            elif locked_session.applied_inference_profile is not None:
                applied = locked_session.applied_inference_profile
                applied_selection = RequestedProfileSelection(
                    profile=RequestedInferenceProfile(
                        model_target_label=applied.model_target_label,
                        reasoning_effort=applied.reasoning_effort,
                        enabled_execution_options=(applied.enabled_execution_options),
                    ),
                    source=InferenceProfileSource.SESSION_LAST_USED,
                )
                expected_selection = normalize_profile_selection_for_agent(
                    active_agent,
                    applied_selection,
                )
                expected = expected_selection.profile
                stale_profile_was_replaced = expected != applied_selection.profile
            else:
                expected = agent_default_inference_profile(active_agent)

            if expected != selected.profile:
                return Success(None)
            if stale_profile_was_replaced and (
                override is None
                or override.source
                not in {
                    InferenceProfileSource.PARENT_RUN,
                    InferenceProfileSource.SPAWN_OVERRIDE,
                }
            ):
                await self.agent_session_repository.set_applied_inference_profile(
                    session,
                    session_id=session_id,
                    model_target_label=expected.model_target_label,
                    reasoning_effort=expected.reasoning_effort,
                    enabled_execution_options=expected.enabled_execution_options,
                )

            option = next(
                (
                    item
                    for item in active_agent.selectable_model_options
                    if item.label == expected.model_target_label
                ),
                None,
            )
            if option is None:
                return Failure(
                    ModelTargetNotFound(model_target_label=expected.model_target_label)
                )
            operation_state = locked_run.model_operation_state or ModelOperationState(
                foreground=None,
                compaction=None,
            )
            existing = operation_state.foreground
            new_foreground = not _reuses_foreground(
                existing, expected, replace_operation=replace_operation
            )
            if new_foreground:
                operation = build_model_operation(
                    option=option,
                    profile=expected,
                    kind=ModelOperationKind.FOREGROUND,
                    operation_id=uuid7().hex,
                    recorded_at=datetime.datetime.now(datetime.UTC),
                )
            else:
                assert existing is not None
                operation = existing
            try:
                selection = await select_model_operation_candidate(
                    session,
                    operation=operation,
                    workspace_id=locked_agent.workspace_id,
                    health_repository=self.model_candidate_health_repository,
                    recorded_at=datetime.datetime.now(datetime.UTC),
                    session_id=session_id,
                    reservation=locked_session.primary_model_reservation,
                )
            except ModelOperationChainExhaustedError as exc:
                exhausted_state = ModelOperationState(
                    foreground=exc.operation,
                    compaction=operation_state.compaction,
                )
                await self.agent_run_repository.update(
                    session,
                    run_id,
                    AgentRunPatch(model_operation_state=exhausted_state),
                )
                return Failure(ModelCandidateChainExhausted(exc.operation))
            if new_foreground and frame.compiled_choices is not None:
                require_selection(
                    frame.compiled_choices, selection.candidate.model_selection
                )
            lightweight_option = frame.compaction_option
            if lightweight_option is None:
                return Failure(
                    ModelTargetNotFound(
                        model_target_label=locked_agent.lightweight_model_label
                    )
                )
            compaction_operation = operation_state.compaction
            new_compaction = (
                compaction_operation is None
                or compaction_operation.terminal_reason is not None
            )
            if (
                compaction_operation is None
                or compaction_operation.terminal_reason is not None
            ):
                compaction_profile = RequestedInferenceProfile(
                    model_target_label=lightweight_option.label,
                    reasoning_effort=None,
                    enabled_execution_options=[],
                )
                compaction_operation = build_model_operation(
                    option=lightweight_option,
                    profile=compaction_profile,
                    kind=ModelOperationKind.COMPACTION,
                    operation_id=uuid7().hex,
                    recorded_at=datetime.datetime.now(datetime.UTC),
                )
            try:
                compaction_selection = await select_model_operation_candidate(
                    session,
                    operation=compaction_operation,
                    workspace_id=locked_agent.workspace_id,
                    health_repository=self.model_candidate_health_repository,
                    recorded_at=datetime.datetime.now(datetime.UTC),
                    session_id=None,
                    reservation=None,
                )
            except ModelOperationChainExhaustedError as exc:
                exhausted_state = ModelOperationState(
                    foreground=selection.operation,
                    compaction=exc.operation,
                )
                await self.agent_run_repository.update(
                    session,
                    run_id,
                    AgentRunPatch(model_operation_state=exhausted_state),
                )
                return Failure(ModelCandidateChainExhausted(exc.operation))
            if new_compaction and frame.compiled_choices is not None:
                require_selection(
                    frame.compiled_choices,
                    compaction_selection.candidate.model_selection,
                )
            next_operation_state = ModelOperationState(
                foreground=selection.operation,
                compaction=compaction_selection.operation,
            )
            await self.agent_run_repository.update(
                session,
                run_id,
                AgentRunPatch(model_operation_state=next_operation_state),
            )
            if selection.reservation_consumed:
                set_reservation = (
                    self.agent_session_repository.set_primary_model_reservation
                )
                cleared = await set_reservation(
                    session,
                    session_id=session_id,
                    reservation=None,
                    expected_reservation_generation=(
                        locked_session.primary_model_reservation.reservation_generation
                        if locked_session.primary_model_reservation is not None
                        else None
                    ),
                )
                if cleared is None:
                    raise CanonicalExecutionWorkDriftError(
                        "Primary reservation changed during transfer"
                    )
        return Success(
            FreshModelPreparation(
                selection=selection,
                compaction_selection=compaction_selection,
                configuration_signature=frame.raw_configuration_signature,
            )
        )

    async def finalize_fresh(
        self,
        *,
        session_id: str,
        run_id: str,
        owner_generation: int,
        operation: ModelOperationSnapshot,
        inference_state: SessionInferenceState,
    ) -> bool:
        """Commit inference after the exact existing owner and operation fence."""
        async with self.session_manager() as session:
            locked_session = await self.agent_session_repository.lock_by_id(
                session,
                session_id,
            )
            locked_run = await self.agent_run_repository.lock_by_id(
                session,
                run_id,
            )
            if locked_session is None or locked_run is None:
                raise ValueError("AgentSession or AgentRun not found")
            if locked_session.owner_generation != owner_generation:
                raise CanonicalExecutionOwnerGenerationStaleError(
                    "Session owner generation is stale"
                )
            persisted = locked_run.model_operation_state
            if (
                persisted is None
                or persisted.foreground is None
                or persisted.foreground.operation_id != operation.operation_id
                or persisted.foreground.cursor != operation.cursor
            ):
                return False
            await self.agent_session_repository.set_inference_state(
                session,
                session_id=session_id,
                inference_state=inference_state,
            )
        return True

    async def prepare_compaction(
        self,
        *,
        agent_id: str,
        session_id: str,
        run_id: str,
        owner_generation: int,
        workspace_id: str,
    ) -> ModelCandidateSelection:
        """Commit selection, but roll exhausted-state writes back on inside error."""
        for _attempt in range(3):
            frame = await self.load_fresh_profile_snapshot(
                agent_id=agent_id,
                session_id=session_id,
                run_id=run_id,
                include_foreground=False,
            )
            async with self.session_manager() as session:
                locked_agent = await self.agent_repository.lock_by_id(session, agent_id)
                locked_session = await self.agent_session_repository.lock_by_id(
                    session,
                    session_id,
                )
                locked_run = await self.agent_run_repository.lock_by_id(
                    session,
                    run_id,
                )
                if locked_agent is None or locked_session is None or locked_run is None:
                    raise ValueError("AgentSession, Agent, or AgentRun not found")
                if locked_session.owner_generation != owner_generation:
                    raise CanonicalExecutionOwnerGenerationStaleError(
                        "Session owner generation is stale"
                    )
                if locked_session.agent_id != agent_id:
                    raise ValueError("AgentSession does not belong to Agent")
                if locked_run.session_id != session_id:
                    raise ValueError("AgentRun does not belong to AgentSession")
                if locked_agent.workspace_id != workspace_id:
                    raise ValueError("Run request does not belong to Agent Workspace")

                if (
                    agent_model_configuration_signature(locked_agent)
                    != frame.raw_configuration_signature
                    or run_model_intent_signature(locked_run)
                    != frame.raw_run_intent_signature
                    or locked_run.model_operation_state != frame.operation_state
                ):
                    continue
                inputs_match = (
                    self.active_capabilities_repository.inputs_match_in_session
                )
                if frame.captured_inputs is not None and not await inputs_match(
                    session, captured=frame.captured_inputs
                ):
                    continue

                operation_state = (
                    locked_run.model_operation_state
                    or ModelOperationState(
                        foreground=None,
                        compaction=None,
                    )
                )
                operation = operation_state.compaction
                new_operation = (
                    operation is None or operation.terminal_reason is not None
                )
                if new_operation:
                    option = frame.compaction_option
                    if option is None:
                        raise ProfileResolutionRuntimeError(
                            profile_resolution_failure(
                                ModelTargetNotFound(
                                    model_target_label=locked_agent.lightweight_model_label
                                )
                            )
                        )
                    profile = RequestedInferenceProfile(
                        model_target_label=option.label,
                        reasoning_effort=None,
                        enabled_execution_options=[],
                    )
                    operation = build_model_operation(
                        option=option,
                        profile=profile,
                        kind=ModelOperationKind.COMPACTION,
                        operation_id=uuid7().hex,
                        recorded_at=datetime.datetime.now(datetime.UTC),
                    )
                assert operation is not None
                try:
                    selection = await select_model_operation_candidate(
                        session,
                        operation=operation,
                        workspace_id=locked_agent.workspace_id,
                        health_repository=self.model_candidate_health_repository,
                        recorded_at=datetime.datetime.now(datetime.UTC),
                        session_id=None,
                        reservation=None,
                    )
                except ModelOperationChainExhaustedError as exc:
                    await self.agent_run_repository.update(
                        session,
                        run_id,
                        AgentRunPatch(
                            model_operation_state=ModelOperationState(
                                foreground=operation_state.foreground,
                                compaction=exc.operation,
                            )
                        ),
                    )
                    raise ProfileResolutionRuntimeError(
                        profile_resolution_failure(
                            ModelCandidateChainExhausted(exc.operation)
                        )
                    ) from exc
                if new_operation and frame.compiled_choices is not None:
                    require_selection(
                        frame.compiled_choices, selection.candidate.model_selection
                    )
                await self.agent_run_repository.update(
                    session,
                    run_id,
                    AgentRunPatch(
                        model_operation_state=ModelOperationState(
                            foreground=operation_state.foreground,
                            compaction=selection.operation,
                        )
                    ),
                )
            return selection
        raise CanonicalExecutionWorkDriftError(
            "Active model inputs changed during compaction preparation"
        )
