"""Genuine PostgreSQL proofs for Worker model commit, rollback and fence groups."""

import asyncio
import dataclasses
import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Literal, NamedTuple

import pytest
import sqlalchemy as sa
from azcommon.result import Failure, Success
from sqlalchemy.exc import IntegrityError

import azents.repos.worker_executor_model as model_module
from azents.core.active_model_capabilities import (
    ActiveModelCapabilitiesUnavailable,
    ActiveModelMetadataUnavailable,
    CapturedStoredChoice,
    CompiledActiveChoices,
    ConfiguredModelIdentity,
)
from azents.core.agent import (
    AgentModelSelection,
    SelectableModelCandidate,
    SelectableModelOption,
)
from azents.core.agent_session_data import AgentSession
from azents.core.enums import AgentRunPhase, AgentRunStatus, ModelCandidateClaimKind
from azents.core.inference_profile import (
    InferenceProfileSource,
    RequestedInferenceProfile,
    SessionInferenceState,
)
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.model_availability import (
    ModelCandidateIdentity as PublicCandidateIdentity,
)
from azents.core.model_availability import PrimaryModelReservation
from azents.core.model_catalog_source import decode_catalog_source
from azents.core.model_execution_options import ModelExecutionOptionId
from azents.core.model_operation import (
    ModelOperationKind,
    ModelOperationSnapshot,
    ModelOperationState,
    ModelOperationTerminalReason,
)
from azents.core.worker_model_profile import (
    ModelCandidateChainExhausted,
    ModelTargetNotFound,
    ProfileResolutionRuntimeError,
    RequestedProfileSelection,
    agent_default_inference_profile,
    normalize_profile_selection_for_agent,
)
from azents.engine.events.types import AgentRunState
from azents.engine.run.failure import FailedRunRetryState
from azents.engine.run.provider_failure import (
    ModelProviderFailure,
    ModelProviderFailureCategory,
    ModelProviderFailureRetryability,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.model_candidate_health import RDBModelCandidateHealth
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.active_model_capabilities import ActiveModelCapabilitiesRepository
from azents.repos.active_model_capabilities_data import CapturedActiveChoiceInputs
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_execution.data import AgentRunCreate, AgentRunPatch
from azents.repos.agent_mailbox import AgentMailboxRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.mailbox.admission import MailboxAdmissionRepository
from azents.repos.model_candidate_health import (
    CandidateHealthRenewal,
    ModelCandidateHealthRepository,
)
from azents.repos.model_candidate_health.data import (
    CandidateClaimTransfer,
    CandidateHealthSettlement,
    ForegroundProbeOutcome,
    ForegroundProbeResult,
    ModelCandidateHealthObservation,
    ModelCandidateIdentity,
)
from azents.repos.session_execution import CanonicalExecutionOwnerGenerationStaleError
from azents.repos.session_execution.repository_test import _create_execution_subject
from azents.repos.terminal_finalization import TerminalRunFinalizationRepository
from azents.repos.worker_executor_model import WorkerExecutorModelOperationRepository
from azents.repos.worker_executor_model_data import FreshModelPreparation
from azents.repos.worker_session import WorkerSessionOperationRepository
from azents.repos.worker_session_data import CanonicalExecutionWorkDriftError
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_model_settings,
)


class ModelActiveCapabilities(ActiveModelCapabilitiesRepository):
    """Deterministic current declarations, independent of saved capability views."""

    def __init__(self) -> None:
        self.captures = 0
        self.revalidations = 0
        self.matches = True
        self.efforts: list[str] = []
        self.identities: list[tuple[ConfiguredModelIdentity, ...]] = []
        self.unavailable: set[str] = set()

    async def capture_exact_choices_in_session(
        self,
        session: ReadSession,
        *,
        workspace_id: str,
        identities: Sequence[ConfiguredModelIdentity],
    ) -> CapturedActiveChoiceInputs:
        del session
        self.captures += 1
        self.identities.append(tuple(identities))
        choices: list[CapturedStoredChoice | ActiveModelMetadataUnavailable] = []
        for identity in identities:
            if identity.model_identifier in self.unavailable:
                choices.append(
                    ActiveModelMetadataUnavailable(identity, "exact_entry_unavailable")
                )
                continue
            source = decode_catalog_source(
                json.dumps(
                    {
                        identity.model_identifier: {
                            "litellm_provider": identity.provider.value,
                            "mode": "responses",
                            "supports_function_calling": True,
                            "supports_reasoning": bool(self.efforts),
                            "reasoning_effort_levels": self.efforts,
                            "supports_web_search": True,
                        }
                    }
                ).encode()
            )
            choices.append(
                CapturedStoredChoice(
                    identity=identity,
                    source_metadata=None,
                    source_models=source.models,
                    supported_execution_options=(),
                    model_developer=None,
                    catalog_id="current-test-catalog",
                )
            )
        return CapturedActiveChoiceInputs(
            workspace_id=workspace_id,
            choices=tuple(choices),
            catalog_choices=(),
            source_metadata=None,
            source_expectations=(),
        )

    async def inputs_match_in_session(
        self, session: WriteSession, *, captured: CapturedActiveChoiceInputs
    ) -> bool:
        del session, captured
        self.revalidations += 1
        return self.matches


class ModelManager:
    """Observe genuine factory completion; narrower compositions share one Session."""

    def __init__(self, manager: SessionManager[WriteSession]) -> None:
        self.manager = manager
        self.sessions: list[WriteSession] = []
        self.active: list[WriteSession] = []
        self.commits = 0
        self.failures = 0

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[WriteSession]:
        assert not self.active, "Nested completed operation inside a model transaction"
        try:
            async with self.manager() as session:
                self.sessions.append(session)
                self.active.append(session)
                try:
                    yield session
                finally:
                    self.active.remove(session)
        except BaseException:
            self.failures += 1
            raise
        else:
            self.commits += 1

    def assert_closed(self) -> None:
        assert not self.active
        assert all(
            not session.write_session.in_transaction() for session in self.sessions
        )


class ModelFault:
    """Record real primitive completion, then fail or pause after reached SQL."""

    def __init__(
        self,
        manager: ModelManager,
        stage: str | None,
        error: BaseException | None,
        pause: bool,
    ) -> None:
        self.manager = manager
        self.stage = stage
        self.error = error
        self.pause = pause
        self.trace: list[str] = []
        self.reached = asyncio.Event()
        self.release = asyncio.Event()
        self.renewal: CandidateHealthRenewal | None = None

    async def point(self, stage: str, session: ReadSession) -> None:
        assert self.manager.active == [session]
        assert session.read_session.in_transaction()
        self.trace.append(stage)
        if self.stage == stage:
            self.reached.set()
            if self.pause:
                await self.release.wait()
            if self.error is not None:
                raise self.error


class ModelAgents(AgentRepository):
    def __init__(self, fault: ModelFault) -> None:
        self.fault = fault

    async def lock_by_id(self, session: WriteSession, agent_id: str) -> Agent | None:
        result = await super().lock_by_id(session, agent_id)
        await self.fault.point("agent_lock", session)
        return result


class ModelSessions(AgentSessionRepository):
    def __init__(self, fault: ModelFault) -> None:
        self.fault = fault

    async def lock_by_id(
        self, session: WriteSession, agent_session_id: str
    ) -> AgentSession | None:
        result = await super().lock_by_id(session, agent_session_id)
        await self.fault.point("session_lock", session)
        return result

    async def set_applied_inference_profile(
        self,
        session: WriteSession,
        *,
        session_id: str,
        model_target_label: str,
        reasoning_effort: ModelReasoningEffort | None,
        enabled_execution_options: list[ModelExecutionOptionId],
    ) -> AgentSession:
        result = await super().set_applied_inference_profile(
            session,
            session_id=session_id,
            model_target_label=model_target_label,
            reasoning_effort=reasoning_effort,
            enabled_execution_options=enabled_execution_options,
        )
        await self.fault.point("profile", session)
        return result

    async def set_primary_model_reservation(
        self,
        session: WriteSession,
        *,
        session_id: str,
        reservation: PrimaryModelReservation | None,
        expected_reservation_generation: int | None,
    ) -> AgentSession | None:
        result = await super().set_primary_model_reservation(
            session,
            session_id=session_id,
            reservation=reservation,
            expected_reservation_generation=expected_reservation_generation,
        )
        await self.fault.point("reservation_clear", session)
        return result

    async def set_inference_state(
        self,
        session: WriteSession,
        *,
        session_id: str,
        inference_state: SessionInferenceState,
    ) -> AgentSession:
        result = await super().set_inference_state(
            session, session_id=session_id, inference_state=inference_state
        )
        await self.fault.point("inference", session)
        return result


class ModelRuns(AgentRunRepository):
    def __init__(self, fault: ModelFault) -> None:
        self.fault = fault

    async def lock_by_id(
        self, session: WriteSession, run_id: str
    ) -> AgentRunState | None:
        result = await super().lock_by_id(session, run_id)
        await self.fault.point("run_lock", session)
        return result

    async def update(
        self, session: WriteSession, run_id: str, patch: AgentRunPatch
    ) -> AgentRunState:
        result = await super().update(session, run_id, patch)
        if "model_operation_state" in patch:
            await self.fault.point("slot", session)
        return result


@dataclasses.dataclass
class ModelHealth(ModelCandidateHealthRepository):
    fault: ModelFault

    async def renew_quota_in_session(
        self, session: ReadSession, identity: ModelCandidateIdentity
    ) -> ModelCandidateHealthObservation:
        result = await super().renew_quota_in_session(session, identity)
        await self.fault.point("renew", session)
        return result

    async def renew_claimed_quota_in_session(
        self,
        session: WriteSession,
        identity: ModelCandidateIdentity,
        *,
        expected_generation: int,
        expected_claim_kind: ModelCandidateClaimKind,
        expected_owner_id: str,
        expected_claim_token: str,
    ) -> CandidateHealthRenewal:
        result = await super().renew_claimed_quota_in_session(
            session,
            identity,
            expected_generation=expected_generation,
            expected_claim_kind=expected_claim_kind,
            expected_owner_id=expected_owner_id,
            expected_claim_token=expected_claim_token,
        )
        self.fault.renewal = result
        await self.fault.point("renew_claimed", session)
        return result

    async def claim_foreground_probe_in_session(
        self, session: WriteSession, identity: ModelCandidateIdentity, *, owner_id: str
    ) -> ForegroundProbeResult:
        result = await super().claim_foreground_probe_in_session(
            session, identity, owner_id=owner_id
        )
        if result.outcome is ForegroundProbeOutcome.CLAIMED:
            await self.fault.point("probe", session)
        return result

    async def transfer_reservation_in_session(
        self,
        session: WriteSession,
        identity: ModelCandidateIdentity,
        *,
        expected_generation: int,
        expected_session_id: str,
        expected_claim_token: str,
        operation_id: str,
    ) -> CandidateClaimTransfer | None:
        result = await super().transfer_reservation_in_session(
            session,
            identity,
            expected_generation=expected_generation,
            expected_session_id=expected_session_id,
            expected_claim_token=expected_claim_token,
            operation_id=operation_id,
        )
        if result is not None:
            await self.fault.point("transfer", session)
        return result


@dataclasses.dataclass(frozen=True)
class ModelGuard(WorkerSessionOperationRepository):
    fault: ModelFault

    async def assert_owner_generation_in_session(
        self, session: WriteSession, *, session_id: str, owner_generation: int
    ) -> None:
        # The marker precedes the actual shared guard, before any model mutation.
        assert self.fault.manager.active == [session]
        self.fault.trace.append("guard")
        await super().assert_owner_generation_in_session(
            session, session_id=session_id, owner_generation=owner_generation
        )


@dataclasses.dataclass(frozen=True)
class ModelFixture:
    manager: ModelManager
    fault: ModelFault
    repository: WorkerExecutorModelOperationRepository
    session_id: str
    run_id: str
    agent_id: str
    workspace_id: str
    generation: int
    options: tuple[SelectableModelOption, ...]

    def identity(self, selection: AgentModelSelection) -> ModelCandidateIdentity:
        return ModelCandidateIdentity(
            workspace_id=self.workspace_id,
            llm_provider_integration_id=selection.llm_provider_integration_id,
            model_identifier=selection.model_identifier,
        )

    @property
    def primary(self) -> ModelCandidateIdentity:
        return self.identity(self.options[0].candidates[0].model_selection)

    @property
    def fallback(self) -> ModelCandidateIdentity:
        return self.identity(self.options[0].candidates[1].model_selection)

    @property
    def lightweight(self) -> ModelCandidateIdentity:
        return self.identity(self.options[1].candidates[0].model_selection)


async def model_fixture(
    manager: SessionManager[WriteSession], name: str
) -> ModelFixture:
    observed = ModelManager(manager)
    fault = ModelFault(observed, None, None, False)
    sessions = ModelSessions(fault)
    runs = ModelRuns(fault)
    agents = ModelAgents(fault)
    async with manager() as session:
        root, agent_id = await _create_execution_subject(session, handle=name)
        agent = await session.write_session.get(RDBAgent, agent_id)
        assert agent is not None and agent.model_selection is not None
        original = AgentModelSelection.model_validate(agent.model_selection)
        selections = [
            make_test_model_selection(
                integration_id=original.llm_provider_integration_id,
                provider=original.provider,
                model_identifier=f"{name}-{suffix}",
            )
            for suffix in ("primary", "fallback", "light")
        ]

        def option(
            label: str, entries: list[AgentModelSelection]
        ) -> SelectableModelOption:
            return SelectableModelOption(
                label=label,
                candidates=[
                    SelectableModelCandidate(
                        model_selection=selection, settings=make_test_model_settings()
                    )
                    for selection in entries
                ],
                subagent_enabled=True,
                subagent_guidance=None,
            )

        options = (
            option("default", selections[:2]),
            option("lightweight", selections[2:]),
            option("alternate", selections[1:2]),
        )
        agent.selectable_model_options = [
            value.model_dump(mode="json") for value in options
        ]
        agent.main_model_label = "default"
        agent.lightweight_model_label = "lightweight"
        await session.write_session.flush()
        generation = await AgentSessionRepository().claim_owner_generation(
            session, root.id
        )
        run = await AgentRunRepository().create(
            session,
            AgentRunCreate(
                session_id=root.id,
                parent_agent_run_id=None,
                scheduled_task_cycle_id=None,
                phase=AgentRunPhase.STREAMING_MODEL,
                status=AgentRunStatus.RUNNING,
            ),
        )
        session_id, run_id, workspace_id = root.id, run.id, root.workspace_id
    mailbox = MailboxRepository()
    terminal = TerminalRunFinalizationRepository(
        observed,
        runs,
        sessions,
        AgentMailboxRepository(
            MailboxAdmissionRepository(observed, mailbox, sessions), sessions
        ),
    )
    guard = ModelGuard(observed, sessions, runs, mailbox, terminal, fault)
    repository = WorkerExecutorModelOperationRepository(
        observed,
        agents,
        sessions,
        runs,
        ModelHealth(observed, fault),
        guard,
        ModelActiveCapabilities(),
    )
    return ModelFixture(
        observed,
        fault,
        repository,
        session_id,
        run_id,
        agent_id,
        workspace_id,
        generation,
        options,
    )


class ModelRows(NamedTuple):
    """Detached Session and Run facts from one authoritative inspection scope."""

    session: AgentSession
    run: AgentRunState


async def model_rows(fixture: ModelFixture) -> ModelRows:
    async with fixture.manager.manager() as session:
        current = await AgentSessionRepository().get_by_id(session, fixture.session_id)
        run = await AgentRunRepository().get_by_id(session, fixture.run_id)
        assert current is not None and run is not None
        return ModelRows(current, run)


async def health(
    fixture: ModelFixture, identity: ModelCandidateIdentity
) -> ModelCandidateHealthObservation:
    return await ModelCandidateHealthRepository(fixture.manager.manager).snapshot(
        identity
    )


async def expire_health(
    fixture: ModelFixture, identity: ModelCandidateIdentity
) -> None:
    async with fixture.manager.manager() as session:
        await session.write_session.execute(
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


async def seed_probe(fixture: ModelFixture, identity: ModelCandidateIdentity) -> None:
    await ModelCandidateHealthRepository(fixture.manager.manager).renew_quota(identity)
    await expire_health(fixture, identity)


async def reserve_primary(fixture: ModelFixture) -> PrimaryModelReservation:
    repository = ModelCandidateHealthRepository(fixture.manager.manager)
    await repository.renew_quota(fixture.primary)
    claim = await repository.claim_reservation(
        fixture.primary, session_id=fixture.session_id
    )
    assert claim.observation.health is not None
    current = claim.observation.health
    assert current.claim_token is not None and current.claim_until is not None
    reservation = PrimaryModelReservation(
        semantic_label="default",
        candidate=PublicCandidateIdentity(
            llm_provider_integration_id=fixture.primary.llm_provider_integration_id,
            model_identifier=fixture.primary.model_identifier,
        ),
        health_generation=current.generation,
        reservation_generation=1,
        claim_token=current.claim_token,
        created_at=claim.observation.server_time,
        expires_at=current.claim_until,
    )
    async with fixture.manager.manager() as session:
        stored = await AgentSessionRepository().set_primary_model_reservation(
            session,
            session_id=fixture.session_id,
            reservation=reservation,
            expected_reservation_generation=None,
        )
        assert stored is not None
    return reservation


async def selected_profile(fixture: ModelFixture) -> RequestedProfileSelection:
    return await fixture.repository.select_requested_profile(
        agent_id=fixture.agent_id, session_id=fixture.session_id, explicit_profile=None
    )


async def prepare(fixture: ModelFixture) -> FreshModelPreparation:
    selected = await selected_profile(fixture)
    result = await fixture.repository.prepare_fresh(
        agent_id=fixture.agent_id,
        session_id=fixture.session_id,
        run_id=fixture.run_id,
        owner_generation=fixture.generation,
        selected=selected,
        override=None,
        replace_operation=False,
    )
    assert isinstance(result, Success) and isinstance(
        result.value, FreshModelPreparation
    )
    fixture.manager.assert_closed()
    return result.value


def inference(operation: ModelOperationSnapshot) -> SessionInferenceState:
    candidate = operation.current_candidate
    return SessionInferenceState(
        model_target_label=operation.semantic_label,
        model_selection=candidate.model_selection,
        model_settings=candidate.settings,
        reasoning_effort=operation.requested_reasoning_effort,
        enabled_execution_options=operation.requested_execution_options,
        effective_context_window_tokens=32000,
        effective_auto_compaction_threshold_tokens=24000,
        resolved_at=datetime.now(UTC),
    )


def quota_failure(
    operation: ModelOperationSnapshot, kind: Literal["sampling", "compaction"]
) -> ModelProviderFailure:
    selection = operation.current_candidate.model_selection
    return ModelProviderFailure(
        operation=kind,
        category=ModelProviderFailureCategory.QUOTA_OR_BILLING,
        retryability=ModelProviderFailureRetryability.USER_ACTION_REQUIRED,
        provider_message="quota exhausted",
        status_code=429,
        provider_code="quota",
        provider_error_type=None,
        provider_error_param=None,
        retry_hint_seconds=None,
        provider=selection.provider.value,
        integration=selection.llm_provider_integration_id,
        model=selection.model_identifier,
    )


async def seed_retry(fixture: ModelFixture) -> None:
    now = datetime.now(UTC)
    retry = FailedRunRetryState(
        failed_attempt_count=1,
        max_retries=3,
        last_user_message="retry",
        last_error_type="ModelProviderFailure",
        last_source="model",
        last_failed_at=now,
        backoff_seconds=1,
        next_retry_at=now,
    )
    async with fixture.manager.manager() as session:
        await AgentRunRepository().update(
            session,
            fixture.run_id,
            AgentRunPatch(retry_state=retry, model_call_started_at=now),
        )


async def stale_profile(fixture: ModelFixture) -> None:
    async with fixture.manager.manager() as session:
        await AgentSessionRepository().set_applied_inference_profile(
            session,
            session_id=fixture.session_id,
            model_target_label="removed",
            reasoning_effort=ModelReasoningEffort.HIGH,
            enabled_execution_options=[],
        )


class ExternalWitness:
    """Typed fake external endpoints must observe zero retained model scopes."""

    def __init__(self, manager: ModelManager) -> None:
        self.manager = manager
        self.calls: list[str] = []

    async def invoke(self, endpoint: str, error: BaseException | None) -> None:
        self.manager.assert_closed()
        self.calls.append(endpoint)
        if error is not None:
            raise error


@pytest.mark.parametrize(
    "explicit,label,source",
    [
        (False, "default", InferenceProfileSource.AGENT_DEFAULT),
        (False, "alternate", InferenceProfileSource.SESSION_LAST_USED),
        (True, "lightweight", InferenceProfileSource.EXPLICIT_INPUT),
    ],
)
async def test_requested_profile_precedence_without_mutation_locks(
    rdb_session_manager: SessionManager[WriteSession],
    explicit: bool,
    label: str,
    source: InferenceProfileSource,
) -> None:
    fixture = await model_fixture(rdb_session_manager, "model-profile-precedence")
    if source is not InferenceProfileSource.AGENT_DEFAULT:
        async with rdb_session_manager() as session:
            await AgentSessionRepository().set_applied_inference_profile(
                session,
                session_id=fixture.session_id,
                model_target_label="alternate",
                reasoning_effort=None,
                enabled_execution_options=[],
            )
    async with rdb_session_manager() as session:
        await AgentSessionRepository().claim_owner_generation(
            session, fixture.session_id
        )
    profile = (
        RequestedInferenceProfile(
            model_target_label="lightweight",
            reasoning_effort=None,
            enabled_execution_options=[],
        )
        if explicit
        else None
    )
    result = await fixture.repository.select_requested_profile(
        agent_id=fixture.agent_id,
        session_id=fixture.session_id,
        explicit_profile=profile,
    )
    assert result.profile.model_target_label == label and result.source is source
    assert fixture.fault.trace == []
    fixture.manager.assert_closed()


async def test_requested_stale_label_normalizes_and_empty_options_keeps_value_error(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    fixture = await model_fixture(rdb_session_manager, "model-profile-stale")
    stale = RequestedInferenceProfile(
        model_target_label="removed",
        reasoning_effort="high",
        enabled_execution_options=[],
    )
    result = await fixture.repository.select_requested_profile(
        agent_id=fixture.agent_id, session_id=fixture.session_id, explicit_profile=stale
    )
    assert result.profile.model_target_label == "default"
    assert (
        result.profile.reasoning_effort is None
        and result.profile.enabled_execution_options == []
    )
    assert result.source is InferenceProfileSource.AGENT_DEFAULT
    with pytest.raises(
        IntegrityError, match="ck_agents_selectable_model_options_shape"
    ):
        async with rdb_session_manager() as session:
            await session.write_session.execute(
                sa.update(RDBAgent)
                .where(RDBAgent.id == fixture.agent_id)
                .values(selectable_model_options=[])
            )
    snapshot = await fixture.repository.load_fresh_profile_snapshot(
        agent_id=fixture.agent_id, session_id=fixture.session_id
    )
    # PostgreSQL forbids persisting empty options; exercise the pure DTO guard.
    empty_agent = snapshot.agent.model_copy(update={"selectable_model_options": []})
    with pytest.raises(ValueError, match="Agent has no selectable model options"):
        agent_default_inference_profile(empty_agent)
    fixture.manager.assert_closed()


@pytest.mark.parametrize("missing", ["agent", "session", "mapping"])
async def test_requested_profile_keeps_missing_and_agent_session_mapping_errors(
    rdb_session_manager: SessionManager[WriteSession], missing: str
) -> None:
    fixture = await model_fixture(rdb_session_manager, "model-profile-invalid")
    agent_id, session_id = fixture.agent_id, fixture.session_id
    if missing == "agent":
        agent_id = "0" * 32
    elif missing == "session":
        session_id = "0" * 32
    else:
        other = await model_fixture(rdb_session_manager, "model-profile-other")
        agent_id = other.agent_id
    with pytest.raises(ValueError):
        await fixture.repository.select_requested_profile(
            agent_id=agent_id, session_id=session_id, explicit_profile=None
        )
    fixture.manager.assert_closed()


async def test_fresh_unlocked_snapshot_and_three_distinct_scopes_before_external(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    fixture = await model_fixture(rdb_session_manager, "model-fresh-three-phases")
    snapshot = await fixture.repository.load_fresh_profile_snapshot(
        agent_id=fixture.agent_id,
        session_id=fixture.session_id,
        run_id=fixture.run_id,
    )
    assert (
        snapshot.agent.id == fixture.agent_id
        and snapshot.session.id == fixture.session_id
    )
    assert fixture.fault.trace == []
    witness = ExternalWitness(fixture.manager)
    for endpoint in ("provider", "Runtime", "Toolkit", "credential", "broadcast"):
        await witness.invoke(endpoint, None)
    selected = RequestedProfileSelection(
        RequestedInferenceProfile(
            model_target_label="default",
            reasoning_effort=None,
            enabled_execution_options=[],
        ),
        InferenceProfileSource.AGENT_DEFAULT,
    )
    result = await fixture.repository.prepare_fresh(
        agent_id=fixture.agent_id,
        session_id=fixture.session_id,
        run_id=fixture.run_id,
        owner_generation=fixture.generation,
        selected=selected,
        override=None,
        replace_operation=False,
        prepared_snapshot=snapshot,
    )
    assert isinstance(result, Success) and isinstance(
        result.value, FreshModelPreparation
    )
    operation = result.value.selection.operation
    await witness.invoke("runtime-materialize", None)
    assert await fixture.repository.finalize_fresh(
        session_id=fixture.session_id,
        run_id=fixture.run_id,
        owner_generation=fixture.generation,
        operation=operation,
        inference_state=inference(operation),
    )
    assert (
        len(fixture.manager.sessions) == 3
        and len({id(session) for session in fixture.manager.sessions}) == 3
    )
    current, run = await model_rows(fixture)
    assert current.inference_state is not None and run.model_operation_state is not None
    assert run.model_operation_state.foreground == operation
    fixture.manager.assert_closed()


async def test_fresh_prewrite_profile_mismatch_has_no_mutations(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    fixture = await model_fixture(rdb_session_manager, "model-prewrite-drift")
    before = await model_rows(fixture)
    selected = RequestedProfileSelection(
        RequestedInferenceProfile(
            model_target_label="alternate",
            reasoning_effort=None,
            enabled_execution_options=[],
        ),
        InferenceProfileSource.SESSION_LAST_USED,
    )
    result = await fixture.repository.prepare_fresh(
        agent_id=fixture.agent_id,
        session_id=fixture.session_id,
        run_id=fixture.run_id,
        owner_generation=fixture.generation,
        selected=selected,
        override=None,
        replace_operation=False,
    )
    assert isinstance(result, Success) and result.value is None
    assert await model_rows(fixture) == before
    assert fixture.fault.trace == ["agent_lock", "session_lock", "run_lock"]
    fixture.manager.assert_closed()


@pytest.mark.parametrize("failure", ["foreground", "missing-lightweight", "compaction"])
async def test_normal_fresh_failures_commit_exact_reached_profile_claim_and_slots(
    rdb_session_manager: SessionManager[WriteSession], failure: str
) -> None:
    fixture = await model_fixture(rdb_session_manager, f"model-fresh-failure-{failure}")
    await stale_profile(fixture)
    reservation = await reserve_primary(fixture) if failure != "foreground" else None
    health_repo = ModelCandidateHealthRepository(rdb_session_manager)
    if failure == "foreground":
        await health_repo.renew_quota(fixture.primary)
        await health_repo.renew_quota(fixture.fallback)
    elif failure == "missing-lightweight":
        async with rdb_session_manager() as session:
            await session.write_session.execute(
                sa.update(RDBAgent)
                .where(RDBAgent.id == fixture.agent_id)
                .values(lightweight_model_label="removed-lightweight")
            )
    else:
        await health_repo.renew_quota(fixture.lightweight)
    selected = await selected_profile(fixture)
    result = await fixture.repository.prepare_fresh(
        agent_id=fixture.agent_id,
        session_id=fixture.session_id,
        run_id=fixture.run_id,
        owner_generation=fixture.generation,
        selected=selected,
        override=None,
        replace_operation=False,
    )
    assert isinstance(result, Failure)
    current, run = await model_rows(fixture)
    assert (
        current.applied_inference_profile is not None
        and current.applied_inference_profile.model_target_label == "default"
    )
    assert current.applied_profile_generation == 2
    if failure == "foreground":
        assert isinstance(result.error, ModelCandidateChainExhausted)
        assert (
            run.model_operation_state is not None
            and run.model_operation_state.foreground is not None
        )
        assert (
            run.model_operation_state.foreground.terminal_reason
            is ModelOperationTerminalReason.CHAIN_EXHAUSTED
        )
    else:
        observation = await health(fixture, fixture.primary)
        assert (
            observation.health is not None
            and observation.health.claim_kind is ModelCandidateClaimKind.PROBE
        )
        assert current.primary_model_reservation == reservation
        assert (
            "transfer" in fixture.fault.trace
            and "reservation_clear" not in fixture.fault.trace
        )
        if failure == "missing-lightweight":
            assert isinstance(result.error, ModelTargetNotFound)
            assert (
                run.model_operation_state is None and "slot" not in fixture.fault.trace
            )
        else:
            assert isinstance(result.error, ModelCandidateChainExhausted)
            assert (
                run.model_operation_state is not None
                and run.model_operation_state.compaction is not None
            )
            assert (
                run.model_operation_state.compaction.terminal_reason
                is ModelOperationTerminalReason.CHAIN_EXHAUSTED
            )
    fixture.manager.assert_closed()


@pytest.mark.parametrize(
    "stage", ["profile", "probe", "transfer", "slot", "reservation_clear"]
)
@pytest.mark.parametrize("cancel", [False, True])
async def test_fresh_exception_after_real_write_rolls_back_entire_prepare_group(
    rdb_session_manager: SessionManager[WriteSession], stage: str, cancel: bool
) -> None:
    fixture = await model_fixture(
        rdb_session_manager, f"model-fresh-rollback-{stage}-{cancel}"
    )
    await stale_profile(fixture)
    if stage in {"transfer", "slot", "reservation_clear"}:
        await reserve_primary(fixture)
    else:
        await seed_probe(fixture, fixture.primary)
    before = await model_rows(fixture)
    before_health = (await health(fixture, fixture.primary)).health
    selected = await selected_profile(fixture)
    error = asyncio.CancelledError() if cancel else RuntimeError("after actual write")
    fixture.fault.stage = stage
    fixture.fault.error = error
    with pytest.raises(type(error)):
        await fixture.repository.prepare_fresh(
            agent_id=fixture.agent_id,
            session_id=fixture.session_id,
            run_id=fixture.run_id,
            owner_generation=fixture.generation,
            selected=selected,
            override=None,
            replace_operation=False,
        )
    assert stage in fixture.fault.trace and fixture.fault.reached.is_set()
    assert await model_rows(fixture) == before
    assert (await health(fixture, fixture.primary)).health == before_health
    fixture.manager.assert_closed()


async def test_successful_reservation_transfer_clear_and_background_no_claim(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    fixture = await model_fixture(rdb_session_manager, "model-transfer-success")
    reservation = await reserve_primary(fixture)
    result = await prepare(fixture)
    claim = result.selection.operation.transferred_probe_claim
    assert result.selection.reservation_consumed and claim is not None
    assert claim.health_generation == reservation.health_generation
    current, run = await model_rows(fixture)
    assert current.primary_model_reservation is None
    assert (
        run.model_operation_state is not None
        and run.model_operation_state.foreground == result.selection.operation
    )
    observation = await health(fixture, fixture.primary)
    assert (
        observation.health is not None
        and observation.health.claim_kind is ModelCandidateClaimKind.PROBE
    )
    assert observation.health.claim_owner_id == result.selection.operation.operation_id
    assert result.compaction_selection.operation.transferred_probe_claim is None
    assert (await health(fixture, fixture.lightweight)).health is None
    fixture.manager.assert_closed()


@pytest.mark.parametrize("kind", ["sampling", "compaction"])
@pytest.mark.parametrize("exhausted", [False, True])
async def test_quota_commits_health_slot_retry_and_start_clears_atomically(
    rdb_session_manager: SessionManager[WriteSession],
    kind: Literal["sampling", "compaction"],
    exhausted: bool,
) -> None:
    fixture = await model_fixture(
        rdb_session_manager, f"model-quota-{kind}-{exhausted}"
    )
    prepared = await prepare(fixture)
    if kind == "sampling" and exhausted:
        await ModelCandidateHealthRepository(rdb_session_manager).renew_quota(
            fixture.fallback
        )
    await seed_retry(fixture)
    operation = (
        prepared.selection.operation
        if kind == "sampling"
        else prepared.compaction_selection.operation
    )
    fixture.fault.trace.clear()
    result = await fixture.repository.advance_after_quota(
        session_id=fixture.session_id,
        run_id=fixture.run_id,
        owner_generation=fixture.generation,
        workspace_id=fixture.workspace_id,
        failure=quota_failure(operation, kind),
    )
    assert result.exhausted is (exhausted or kind == "compaction")
    assert fixture.fault.trace[:3] == ["guard", "session_lock", "run_lock"]
    assert "renew" in fixture.fault.trace and "slot" in fixture.fault.trace
    current, run = await model_rows(fixture)
    assert run.retry_state is None and run.model_call_started_at is None
    assert run.model_operation_state is not None
    stored = (
        run.model_operation_state.foreground
        if kind == "sampling"
        else run.model_operation_state.compaction
    )
    assert stored == result.operation
    observation = await health(
        fixture, fixture.primary if kind == "sampling" else fixture.lightweight
    )
    assert observation.health is not None and observation.health.generation == 1
    assert observation.health.cooldown_until - observation.server_time > timedelta(
        minutes=4
    )
    assert current.owner_generation == fixture.generation
    fixture.manager.assert_closed()


@pytest.mark.parametrize("stage", ["renew", "probe", "slot"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_quota_failure_after_real_sql_rolls_back_health_claim_slot_and_clears(
    rdb_session_manager: SessionManager[WriteSession], stage: str, cancel: bool
) -> None:
    fixture = await model_fixture(
        rdb_session_manager, f"model-quota-fault-{stage}-{cancel}"
    )
    prepared = await prepare(fixture)
    await seed_probe(fixture, fixture.fallback)
    await seed_retry(fixture)
    before = await model_rows(fixture)
    before_fallback = (await health(fixture, fixture.fallback)).health
    fixture.fault.stage = stage
    fixture.fault.error = (
        asyncio.CancelledError() if cancel else RuntimeError("quota rollback")
    )
    with pytest.raises(type(fixture.fault.error)):
        await fixture.repository.advance_after_quota(
            session_id=fixture.session_id,
            run_id=fixture.run_id,
            owner_generation=fixture.generation,
            workspace_id=fixture.workspace_id,
            failure=quota_failure(prepared.selection.operation, "sampling"),
        )
    assert fixture.fault.reached.is_set()
    assert await model_rows(fixture) == before
    assert (await health(fixture, fixture.primary)).health is None
    assert (await health(fixture, fixture.fallback)).health == before_fallback
    fixture.manager.assert_closed()


async def test_quota_uses_stale_claimed_renewal_observation_without_new_rejection(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    fixture = await model_fixture(rdb_session_manager, "model-quota-stale-claim")
    await seed_probe(fixture, fixture.primary)
    prepared = await prepare(fixture)
    assert prepared.selection.operation.transferred_probe_claim is not None
    newer = await ModelCandidateHealthRepository(rdb_session_manager).renew_quota(
        fixture.primary
    )
    result = await fixture.repository.advance_after_quota(
        session_id=fixture.session_id,
        run_id=fixture.run_id,
        owner_generation=fixture.generation,
        workspace_id=fixture.workspace_id,
        failure=quota_failure(prepared.selection.operation, "sampling"),
    )
    assert (
        fixture.fault.renewal is not None
        and fixture.fault.renewal[0] is CandidateHealthSettlement.STALE
    )
    assert not result.exhausted and result.operation.cursor == 1
    assert (await health(fixture, fixture.primary)).health == newer.health
    fixture.manager.assert_closed()


@pytest.mark.parametrize(
    "invalid", ["missing", "stale", "run", "state", "slot", "route"]
)
async def test_quota_guard_and_exact_prewrite_errors_preserve_rows(
    rdb_session_manager: SessionManager[WriteSession], invalid: str
) -> None:
    fixture = await model_fixture(rdb_session_manager, f"model-quota-invalid-{invalid}")
    prepared = await prepare(fixture)
    session_id, run_id = fixture.session_id, fixture.run_id
    failure = quota_failure(prepared.selection.operation, "sampling")
    if invalid == "missing":
        session_id = "0" * 32
    elif invalid == "stale":
        async with rdb_session_manager() as session:
            await AgentSessionRepository().claim_owner_generation(
                session, fixture.session_id
            )
    elif invalid == "run":
        run_id = "0" * 32
    elif invalid in {"state", "slot"}:
        async with rdb_session_manager() as session:
            await AgentRunRepository().update(
                session,
                run_id,
                AgentRunPatch(
                    model_operation_state=None
                    if invalid == "state"
                    else ModelOperationState(
                        foreground=None,
                        compaction=prepared.compaction_selection.operation,
                    )
                ),
            )
    else:
        failure.route_model = "wrong-route"
    before = await model_rows(fixture)
    fixture.fault.trace.clear()
    expected = (
        CanonicalExecutionOwnerGenerationStaleError
        if invalid == "stale"
        else CanonicalExecutionWorkDriftError
        if invalid in {"state", "slot", "route"}
        else ValueError
    )
    with pytest.raises(expected):
        await fixture.repository.advance_after_quota(
            session_id=session_id,
            run_id=run_id,
            owner_generation=fixture.generation,
            workspace_id=fixture.workspace_id,
            failure=failure,
        )
    assert fixture.fault.trace[0] == "guard" and "renew" not in fixture.fault.trace
    assert await model_rows(fixture) == before
    assert (await health(fixture, fixture.primary)).health is None
    fixture.manager.assert_closed()


async def test_quota_does_not_add_run_session_identity_check(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    fixture = await model_fixture(rdb_session_manager, "model-quota-source")
    other = await model_fixture(rdb_session_manager, "model-quota-other-session")
    prepared = await prepare(fixture)
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBAgentRun)
            .where(RDBAgentRun.id == fixture.run_id)
            .values(session_id=other.session_id, run_index=2)
        )
    result = await fixture.repository.advance_after_quota(
        session_id=fixture.session_id,
        run_id=fixture.run_id,
        owner_generation=fixture.generation,
        workspace_id=fixture.workspace_id,
        failure=quota_failure(prepared.selection.operation, "sampling"),
    )
    assert not result.exhausted and result.operation.cursor == 1
    fixture.manager.assert_closed()


@pytest.mark.parametrize("drift", ["id", "cursor", "missing"])
async def test_final_inference_operation_fence_retains_prior_preparation_commit(
    rdb_session_manager: SessionManager[WriteSession], drift: str
) -> None:
    fixture = await model_fixture(rdb_session_manager, f"model-final-drift-{drift}")
    prepared = await prepare(fixture)
    expected = prepared.selection.operation
    changed = (
        expected.model_copy(update={"operation_id": "f" * 32})
        if drift == "id"
        else expected.model_copy(update={"cursor": 1})
        if drift == "cursor"
        else None
    )
    async with rdb_session_manager() as session:
        await AgentRunRepository().update(
            session,
            fixture.run_id,
            AgentRunPatch(
                model_operation_state=ModelOperationState(
                    foreground=changed,
                    compaction=prepared.compaction_selection.operation,
                )
            ),
        )
    before = await model_rows(fixture)
    assert not await fixture.repository.finalize_fresh(
        session_id=fixture.session_id,
        run_id=fixture.run_id,
        owner_generation=fixture.generation,
        operation=expected,
        inference_state=inference(expected),
    )
    assert (
        await model_rows(fixture) == before and "inference" not in fixture.fault.trace
    )
    fixture.manager.assert_closed()


@pytest.mark.parametrize("cancel", [False, True])
async def test_final_inference_write_rollback_preserves_previous_claim_and_slot(
    rdb_session_manager: SessionManager[WriteSession], cancel: bool
) -> None:
    fixture = await model_fixture(rdb_session_manager, "model-final-rollback")
    await reserve_primary(fixture)
    prepared = await prepare(fixture)
    before = await model_rows(fixture)
    before_health = (await health(fixture, fixture.primary)).health
    fixture.fault.stage = "inference"
    fixture.fault.error = (
        asyncio.CancelledError() if cancel else RuntimeError("inference rollback")
    )
    with pytest.raises(type(fixture.fault.error)):
        await fixture.repository.finalize_fresh(
            session_id=fixture.session_id,
            run_id=fixture.run_id,
            owner_generation=fixture.generation,
            operation=prepared.selection.operation,
            inference_state=inference(prepared.selection.operation),
        )
    assert fixture.fault.reached.is_set() and await model_rows(fixture) == before
    assert (await health(fixture, fixture.primary)).health == before_health
    fixture.manager.assert_closed()


@pytest.mark.parametrize("mode", ["success", "missing", "exhausted"])
async def test_compaction_background_commits_success_but_inside_error_rolls_back_slot(
    rdb_session_manager: SessionManager[WriteSession], mode: str
) -> None:
    fixture = await model_fixture(rdb_session_manager, f"model-compaction-{mode}")
    if mode == "missing":
        async with rdb_session_manager() as session:
            await session.write_session.execute(
                sa.update(RDBAgent)
                .where(RDBAgent.id == fixture.agent_id)
                .values(lightweight_model_label="removed")
            )
    elif mode == "exhausted":
        await ModelCandidateHealthRepository(rdb_session_manager).renew_quota(
            fixture.lightweight
        )
    before = await model_rows(fixture)
    if mode == "success":
        selection = await fixture.repository.prepare_compaction(
            agent_id=fixture.agent_id,
            session_id=fixture.session_id,
            run_id=fixture.run_id,
            owner_generation=fixture.generation,
            workspace_id=fixture.workspace_id,
        )
        assert selection.operation.kind is ModelOperationKind.COMPACTION
        assert (
            selection.operation.transferred_probe_claim is None
            and not selection.reservation_consumed
        )
        assert (await health(fixture, fixture.lightweight)).health is None
        witness = ExternalWitness(fixture.manager)
        with pytest.raises(RuntimeError, match="external resolution failure"):
            await witness.invoke(
                "credential-runtime", RuntimeError("external resolution failure")
            )
        current, run = await model_rows(fixture)
        assert (
            current == before[0]
            and run.model_operation_state is not None
            and run.model_operation_state.compaction == selection.operation
        )
    else:
        with pytest.raises(ProfileResolutionRuntimeError) as failure:
            await fixture.repository.prepare_compaction(
                agent_id=fixture.agent_id,
                session_id=fixture.session_id,
                run_id=fixture.run_id,
                owner_generation=fixture.generation,
                workspace_id=fixture.workspace_id,
            )
        assert failure.value.failure_code == (
            "model_target_not_found"
            if mode == "missing"
            else "model_candidate_chain_exhausted"
        )
        assert await model_rows(fixture) == before
        assert ("slot" in fixture.fault.trace) == (mode == "exhausted")
    fixture.manager.assert_closed()


async def test_task_cancel_after_profile_write_resolves_prepare_transaction(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    fixture = await model_fixture(rdb_session_manager, "model-task-cancel")
    await stale_profile(fixture)
    before = await model_rows(fixture)
    selected = await selected_profile(fixture)
    fixture.fault.stage = "profile"
    fixture.fault.pause = True
    task = asyncio.create_task(
        fixture.repository.prepare_fresh(
            agent_id=fixture.agent_id,
            session_id=fixture.session_id,
            run_id=fixture.run_id,
            owner_generation=fixture.generation,
            selected=selected,
            override=None,
            replace_operation=False,
        )
    )
    try:
        await asyncio.wait_for(fixture.fault.reached.wait(), timeout=5)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert task.cancelled() and await model_rows(fixture) == before
    fixture.manager.assert_closed()


async def test_missing_lightweight_commits_actual_half_open_probe_without_slot(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    fixture = await model_fixture(rdb_session_manager, "model-light-missing-probe")
    await stale_profile(fixture)
    await seed_probe(fixture, fixture.primary)
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBAgent)
            .where(RDBAgent.id == fixture.agent_id)
            .values(lightweight_model_label="missing-light")
        )
    selected = await selected_profile(fixture)
    result = await fixture.repository.prepare_fresh(
        agent_id=fixture.agent_id,
        session_id=fixture.session_id,
        run_id=fixture.run_id,
        owner_generation=fixture.generation,
        selected=selected,
        override=None,
        replace_operation=False,
    )
    assert isinstance(result, Failure) and isinstance(result.error, ModelTargetNotFound)
    current, run = await model_rows(fixture)
    observation = await health(fixture, fixture.primary)
    assert observation.health is not None
    assert observation.health.generation == 2
    assert observation.health.claim_kind is ModelCandidateClaimKind.PROBE
    assert observation.health.claim_token is not None
    assert observation.health.claim_owner_id is not None
    assert run.model_operation_state is None
    assert current.primary_model_reservation is None
    assert current.applied_profile_generation == 2
    assert "probe" in fixture.fault.trace
    assert "slot" not in fixture.fault.trace
    fixture.manager.assert_closed()


@pytest.mark.parametrize(
    "source",
    [
        InferenceProfileSource.PARENT_RUN,
        InferenceProfileSource.SPAWN_OVERRIDE,
        InferenceProfileSource.RETRY_ORIGINAL,
    ],
)
async def test_stale_override_source_and_replacement_policy_remain_unchanged(
    rdb_session_manager: SessionManager[WriteSession],
    source: InferenceProfileSource,
) -> None:
    fixture = await model_fixture(rdb_session_manager, "model-stale-override")
    await stale_profile(fixture)
    snapshot = await fixture.repository.load_fresh_profile_snapshot(
        agent_id=fixture.agent_id, session_id=fixture.session_id
    )
    override = RequestedProfileSelection(
        RequestedInferenceProfile(
            model_target_label="removed",
            reasoning_effort=ModelReasoningEffort.HIGH,
            enabled_execution_options=[ModelExecutionOptionId.ULTRAFAST],
        ),
        source,
    )
    selected = normalize_profile_selection_for_agent(snapshot.agent, override)
    assert selected.source is source
    assert selected.profile.reasoning_effort is None
    assert selected.profile.enabled_execution_options == []
    result = await fixture.repository.prepare_fresh(
        agent_id=fixture.agent_id,
        session_id=fixture.session_id,
        run_id=fixture.run_id,
        owner_generation=fixture.generation,
        selected=selected,
        override=override,
        replace_operation=False,
    )
    assert isinstance(result, Success) and result.value is not None
    current, _ = await model_rows(fixture)
    assert current.applied_inference_profile is not None
    if source is InferenceProfileSource.RETRY_ORIGINAL:
        assert current.applied_inference_profile.model_target_label == "default"
        assert current.applied_profile_generation == 2
    else:
        assert current.applied_inference_profile.model_target_label == "removed"
        assert current.applied_profile_generation == 1
    fixture.manager.assert_closed()


@pytest.mark.parametrize("cancel", [False, True])
async def test_fresh_prepared_commit_survives_external_resolution_failure(
    rdb_session_manager: SessionManager[WriteSession],
    cancel: bool,
) -> None:
    fixture = await model_fixture(rdb_session_manager, "model-external-failure")
    await reserve_primary(fixture)
    await prepare(fixture)
    before = await model_rows(fixture)
    before_health = (await health(fixture, fixture.primary)).health
    error = asyncio.CancelledError() if cancel else RuntimeError("resolution failed")
    witness = ExternalWitness(fixture.manager)
    with pytest.raises(type(error)):
        await witness.invoke("provider-runtime-credential", error)
    assert await model_rows(fixture) == before
    assert (await health(fixture, fixture.primary)).health == before_health
    assert before.session.primary_model_reservation is None
    assert before.run.model_operation_state is not None
    fixture.manager.assert_closed()


@pytest.mark.parametrize("cancel", [False, True])
async def test_compaction_fault_after_actual_slot_write_rolls_back(
    rdb_session_manager: SessionManager[WriteSession],
    cancel: bool,
) -> None:
    fixture = await model_fixture(rdb_session_manager, "model-compaction-slot-fault")
    before = await model_rows(fixture)
    error = asyncio.CancelledError() if cancel else RuntimeError("slot failed")
    fixture.fault.stage = "slot"
    fixture.fault.error = error
    with pytest.raises(type(error)):
        await fixture.repository.prepare_compaction(
            agent_id=fixture.agent_id,
            session_id=fixture.session_id,
            run_id=fixture.run_id,
            owner_generation=fixture.generation,
            workspace_id=fixture.workspace_id,
        )
    assert fixture.fault.reached.is_set()
    assert await model_rows(fixture) == before
    assert (await health(fixture, fixture.lightweight)).health is None
    fixture.manager.assert_closed()


class _BrokenRead(ModelAgents):
    async def get_by_id(self, session: ReadSession, agent_id: str) -> Agent | None:
        result = await super().get_by_id(session, agent_id)
        await self.fault.point("read", session)
        return result


@pytest.mark.parametrize("cancel", [False, True])
async def test_actual_snapshot_read_error_or_cancel_closes_before_external_work(
    rdb_session_manager: SessionManager[WriteSession],
    cancel: bool,
) -> None:
    fixture = await model_fixture(rdb_session_manager, "model-read-fault")
    error = asyncio.CancelledError() if cancel else RuntimeError("read failed")
    fixture.fault.stage = "read"
    fixture.fault.error = error
    repository = dataclasses.replace(
        fixture.repository, agent_repository=_BrokenRead(fixture.fault)
    )
    with pytest.raises(type(error)):
        await repository.load_fresh_profile_snapshot(
            agent_id=fixture.agent_id, session_id=fixture.session_id
        )
    assert fixture.fault.reached.is_set()
    witness = ExternalWitness(fixture.manager)
    for endpoint in ("provider", "Runtime", "Toolkit", "credential", "broadcast"):
        await witness.invoke(endpoint, None)
    fixture.manager.assert_closed()


@pytest.mark.parametrize("operation", ["fresh", "final", "compaction"])
@pytest.mark.parametrize("invalid", ["stale", "missing-run"])
async def test_model_existing_generation_and_missing_run_errors_are_prewrite(
    rdb_session_manager: SessionManager[WriteSession],
    operation: Literal["fresh", "final", "compaction"],
    invalid: str,
) -> None:
    fixture = await model_fixture(rdb_session_manager, "model-prepare-identity")
    prepared = await prepare(fixture)
    if invalid == "stale":
        async with rdb_session_manager() as session:
            await AgentSessionRepository().claim_owner_generation(
                session, fixture.session_id
            )
    run_id = "0" * 32 if invalid == "missing-run" else fixture.run_id
    selected = await selected_profile(fixture)
    before = await model_rows(fixture)
    expected = (
        CanonicalExecutionOwnerGenerationStaleError
        if invalid == "stale"
        else ValueError
    )
    with pytest.raises(expected):
        if operation == "fresh":
            await fixture.repository.prepare_fresh(
                agent_id=fixture.agent_id,
                session_id=fixture.session_id,
                run_id=run_id,
                owner_generation=fixture.generation,
                selected=selected,
                override=None,
                replace_operation=False,
            )
        elif operation == "final":
            await fixture.repository.finalize_fresh(
                session_id=fixture.session_id,
                run_id=run_id,
                owner_generation=fixture.generation,
                operation=prepared.selection.operation,
                inference_state=inference(prepared.selection.operation),
            )
        else:
            await fixture.repository.prepare_compaction(
                agent_id=fixture.agent_id,
                session_id=fixture.session_id,
                run_id=run_id,
                owner_generation=fixture.generation,
                workspace_id=fixture.workspace_id,
            )
    assert await model_rows(fixture) == before
    fixture.manager.assert_closed()


async def test_final_inference_does_not_add_agent_configuration_fence(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    fixture = await model_fixture(rdb_session_manager, "model-final-agent-change")
    prepared = await prepare(fixture)
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBAgent)
            .where(RDBAgent.id == fixture.agent_id)
            .values(main_model_label="alternate")
        )
    assert await fixture.repository.finalize_fresh(
        session_id=fixture.session_id,
        run_id=fixture.run_id,
        owner_generation=fixture.generation,
        operation=prepared.selection.operation,
        inference_state=inference(prepared.selection.operation),
    )
    current, _ = await model_rows(fixture)
    assert current.inference_state is not None
    assert current.inference_state.model_target_label == "default"
    fixture.manager.assert_closed()


@pytest.mark.parametrize("cancel", [False, True])
async def test_claimed_quota_renewal_actual_write_rolls_back_with_previous_authority(
    rdb_session_manager: SessionManager[WriteSession],
    cancel: bool,
) -> None:
    fixture = await model_fixture(rdb_session_manager, "model-claimed-quota-rollback")
    await seed_probe(fixture, fixture.primary)
    prepared = await prepare(fixture)
    await seed_retry(fixture)
    before = await model_rows(fixture)
    previous_health = (await health(fixture, fixture.primary)).health
    error = asyncio.CancelledError() if cancel else RuntimeError("claimed renew failed")
    fixture.fault.stage = "renew_claimed"
    fixture.fault.error = error
    with pytest.raises(type(error)):
        await fixture.repository.advance_after_quota(
            session_id=fixture.session_id,
            run_id=fixture.run_id,
            owner_generation=fixture.generation,
            workspace_id=fixture.workspace_id,
            failure=quota_failure(prepared.selection.operation, "sampling"),
        )
    assert fixture.fault.renewal is not None
    assert fixture.fault.renewal[0] is CandidateHealthSettlement.APPLIED
    assert fixture.fault.reached.is_set()
    assert await model_rows(fixture) == before
    assert (await health(fixture, fixture.primary)).health == previous_health
    fixture.manager.assert_closed()


@pytest.mark.parametrize("invalid", ["workspace", "agent", "run-session"])
async def test_compaction_preserves_existing_workspace_and_mapping_guards(
    rdb_session_manager: SessionManager[WriteSession],
    invalid: str,
) -> None:
    fixture = await model_fixture(rdb_session_manager, "model-compaction-guard")
    agent_id, workspace_id = fixture.agent_id, fixture.workspace_id
    if invalid == "workspace":
        workspace_id = "f" * 32
    else:
        other = await model_fixture(rdb_session_manager, "model-compaction-guard-other")
        if invalid == "agent":
            agent_id = other.agent_id
        else:
            async with rdb_session_manager() as session:
                await session.write_session.execute(
                    sa.update(RDBAgentRun)
                    .where(RDBAgentRun.id == fixture.run_id)
                    .values(session_id=other.session_id, run_index=2)
                )
    before = await model_rows(fixture)
    with pytest.raises(ValueError):
        await fixture.repository.prepare_compaction(
            agent_id=agent_id,
            session_id=fixture.session_id,
            run_id=fixture.run_id,
            owner_generation=fixture.generation,
            workspace_id=workspace_id,
        )
    assert await model_rows(fixture) == before
    assert "slot" not in fixture.fault.trace
    fixture.manager.assert_closed()


@pytest.mark.parametrize("missing", ["agent", "session"])
async def test_profile_snapshot_missing_value_error_follows_scope_completion(
    rdb_session_manager: SessionManager[WriteSession],
    missing: str,
) -> None:
    fixture = await model_fixture(rdb_session_manager, "model-snapshot-missing")
    with pytest.raises(ValueError, match="AgentSession or Agent not found"):
        await fixture.repository.load_fresh_profile_snapshot(
            agent_id="0" * 32 if missing == "agent" else fixture.agent_id,
            session_id="0" * 32 if missing == "session" else fixture.session_id,
        )
    await ExternalWitness(fixture.manager).invoke("provider", None)
    fixture.manager.assert_closed()


async def test_new_foreground_and_compaction_compile_before_both_normalizations(
    rdb_session_manager: SessionManager[WriteSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stale saved capabilities never enter new profile normalization."""
    fixture = await model_fixture(rdb_session_manager, "active-before-normalization")
    active = fixture.repository.active_capabilities_repository
    assert isinstance(active, ModelActiveCapabilities)
    active.efforts = ["xhigh", "max"]
    async with fixture.manager() as session:
        original = await fixture.repository.agent_repository.get_by_id(
            session, fixture.agent_id
        )
    assert original is not None
    before = original.model_dump(mode="json")
    seen = []
    compile_original = model_module.compile_capture
    normalize_original = model_module.normalize_profile_selection_for_agent

    def compile_after_transaction(
        captured: CapturedActiveChoiceInputs,
        *,
        selections: Sequence[AgentModelSelection],
    ) -> CompiledActiveChoices:
        assert not fixture.manager.active
        return compile_original(captured, selections=selections)

    def normalize_compiled(
        agent: Agent, selected: RequestedProfileSelection
    ) -> RequestedProfileSelection:
        caps = (
            agent.selectable_model_options[0]
            .candidates[0]
            .model_selection.normalized_capabilities
        )
        seen.append(tuple(caps.reasoning.effort_levels))
        assert caps.capability_schema_version == 3
        assert caps.reasoning.effort_levels == [
            ModelReasoningEffort.XHIGH,
            ModelReasoningEffort.MAX,
        ]
        return normalize_original(agent, selected)

    monkeypatch.setattr(model_module, "compile_capture", compile_after_transaction)
    monkeypatch.setattr(
        model_module, "normalize_profile_selection_for_agent", normalize_compiled
    )
    override = RequestedProfileSelection(
        RequestedInferenceProfile(
            model_target_label="removed",
            reasoning_effort=ModelReasoningEffort.MAX,
            enabled_execution_options=[],
        ),
        InferenceProfileSource.PARENT_RUN,
    )
    frame = await fixture.repository.load_fresh_profile_snapshot(
        agent_id=fixture.agent_id,
        session_id=fixture.session_id,
        run_id=fixture.run_id,
        override=override,
    )
    selected = model_module.normalize_profile_selection_for_agent(frame.agent, override)
    # The fallback uses the Agent's raw default intent; capability compilation
    # precedes deciding whether that intent remains valid.
    result = await fixture.repository.prepare_fresh(
        agent_id=fixture.agent_id,
        session_id=fixture.session_id,
        run_id=fixture.run_id,
        owner_generation=fixture.generation,
        selected=selected,
        override=override,
        replace_operation=False,
        prepared_snapshot=frame,
    )
    assert isinstance(result, Success) and result.value is not None
    for operation in (
        result.value.selection.operation,
        result.value.compaction_selection.operation,
    ):
        assert operation.candidates[
            0
        ].model_selection.normalized_capabilities.reasoning.effort_levels == [
            ModelReasoningEffort.XHIGH,
            ModelReasoningEffort.MAX,
        ]
    assert len(seen) == 2
    assert active.captures == 1 and active.revalidations == 1
    async with fixture.manager() as session:
        persisted = await fixture.repository.agent_repository.get_by_id(
            session, fixture.agent_id
        )
    assert persisted is not None and persisted.model_dump(mode="json") == before


async def test_frozen_reuse_and_quota_advance_do_not_relookup_active_metadata(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    fixture = await model_fixture(rdb_session_manager, "active-frozen-quota")
    first = await prepare(fixture)
    active = fixture.repository.active_capabilities_repository
    assert isinstance(active, ModelActiveCapabilities)
    calls = active.captures, active.revalidations
    frozen = first.selection.operation.candidates
    active.efforts = ["max"]
    active.matches = False
    advanced = await fixture.repository.advance_after_quota(
        session_id=fixture.session_id,
        run_id=fixture.run_id,
        owner_generation=fixture.generation,
        workspace_id=fixture.workspace_id,
        failure=quota_failure(first.selection.operation, "sampling"),
    )
    assert advanced.operation.cursor == 1
    selected = await fixture.repository.select_requested_profile(
        agent_id=fixture.agent_id,
        session_id=fixture.session_id,
        run_id=fixture.run_id,
        explicit_profile=None,
    )
    frame = await fixture.repository.load_fresh_profile_snapshot(
        agent_id=fixture.agent_id,
        session_id=fixture.session_id,
        run_id=fixture.run_id,
    )
    assert frame.captured_inputs is None and frame.compiled_choices is None
    reused = await fixture.repository.prepare_fresh(
        agent_id=fixture.agent_id,
        session_id=fixture.session_id,
        run_id=fixture.run_id,
        owner_generation=fixture.generation,
        selected=selected,
        override=None,
        replace_operation=False,
        prepared_snapshot=frame,
    )
    assert isinstance(reused, Success) and reused.value is not None
    assert (
        reused.value.selection.operation.operation_id == advanced.operation.operation_id
    )
    assert reused.value.selection.operation.cursor == 1
    assert reused.value.selection.operation.candidates == frozen
    assert (
        reused.value.compaction_selection.operation
        == first.compaction_selection.operation
    )
    assert (active.captures, active.revalidations) == calls


async def test_source_input_change_is_prewrite_drift_not_mixed_operation(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    fixture = await model_fixture(rdb_session_manager, "active-input-drift")
    frame = await fixture.repository.load_fresh_profile_snapshot(
        agent_id=fixture.agent_id,
        session_id=fixture.session_id,
        run_id=fixture.run_id,
    )
    active = fixture.repository.active_capabilities_repository
    assert isinstance(active, ModelActiveCapabilities)
    active.matches = False
    before = await model_rows(fixture)
    result = await fixture.repository.prepare_fresh(
        agent_id=fixture.agent_id,
        session_id=fixture.session_id,
        run_id=fixture.run_id,
        owner_generation=fixture.generation,
        selected=RequestedProfileSelection(
            agent_default_inference_profile(frame.agent),
            InferenceProfileSource.AGENT_DEFAULT,
        ),
        override=None,
        replace_operation=False,
        prepared_snapshot=frame,
    )
    assert isinstance(result, Success) and result.value is None
    assert await model_rows(fixture) == before
    assert active.revalidations == 1
    assert "slot" not in fixture.fault.trace


async def test_standalone_compaction_captures_only_new_lightweight_then_freezes(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    fixture = await model_fixture(rdb_session_manager, "active-compaction-only")
    active = fixture.repository.active_capabilities_repository
    assert isinstance(active, ModelActiveCapabilities)
    active.efforts = ["max"]
    first = await fixture.repository.prepare_compaction(
        agent_id=fixture.agent_id,
        session_id=fixture.session_id,
        run_id=fixture.run_id,
        owner_generation=fixture.generation,
        workspace_id=fixture.workspace_id,
    )
    assert active.identities == [
        (
            ConfiguredModelIdentity.from_selection(
                fixture.options[1].candidates[0].model_selection
            ),
        )
    ]
    assert (
        first.candidate.model_selection.normalized_capabilities.reasoning.effort_levels
        == [ModelReasoningEffort.MAX]
    )
    active.efforts = []
    active.matches = False
    second = await fixture.repository.prepare_compaction(
        agent_id=fixture.agent_id,
        session_id=fixture.session_id,
        run_id=fixture.run_id,
        owner_generation=fixture.generation,
        workspace_id=fixture.workspace_id,
    )
    assert second.operation == first.operation
    assert active.captures == 1 and active.revalidations == 1


async def test_unavailable_selected_metadata_fails_without_model_substitution(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    fixture = await model_fixture(rdb_session_manager, "active-unavailable")
    active = fixture.repository.active_capabilities_repository
    assert isinstance(active, ModelActiveCapabilities)
    active.unavailable.add(fixture.primary.model_identifier)
    before = await model_rows(fixture)
    with pytest.raises(ActiveModelCapabilitiesUnavailable) as error:
        await prepare(fixture)
    assert (
        error.value.diagnostic.identity.model_identifier
        == fixture.primary.model_identifier
    )
    assert await model_rows(fixture) == before


@pytest.mark.parametrize("change", ["metadata", "settings", "order", "identity"])
async def test_locked_prepare_fences_user_configuration_not_metadata(
    rdb_session_manager: SessionManager[WriteSession],
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    fixture = await model_fixture(rdb_session_manager, f"active-config-{change}")
    frame = await fixture.repository.load_fresh_profile_snapshot(
        agent_id=fixture.agent_id,
        session_id=fixture.session_id,
        run_id=fixture.run_id,
    )
    original_lock = fixture.repository.agent_repository.lock_by_id

    async def changed_lock(session: WriteSession, agent_id: str) -> Agent | None:
        agent = await original_lock(session, agent_id)
        assert agent is not None
        options = list(agent.selectable_model_options)
        option = options[0]
        candidate = option.candidates[0]
        if change == "metadata":
            selected = candidate.model_selection.model_copy(
                update={
                    "model_display_name": "New display-only metadata",
                    "source_metadata": {"diagnostics": "changed"},
                    "model_snapshot": {"new": "compiled"},
                }
            )
            option = option.model_copy(
                update={
                    "candidates": [
                        candidate.model_copy(update={"model_selection": selected}),
                        *option.candidates[1:],
                    ]
                }
            )
        elif change == "settings":
            option = option.model_copy(
                update={
                    "candidates": [
                        candidate.model_copy(
                            update={
                                "settings": candidate.settings.model_copy(
                                    update={"max_output_tokens": 777}
                                )
                            }
                        ),
                        *option.candidates[1:],
                    ]
                }
            )
        elif change == "order":
            option = option.model_copy(
                update={"candidates": list(reversed(option.candidates))}
            )
        else:
            selected = candidate.model_selection.model_copy(
                update={"model_identifier": "changed-by-user"}
            )
            option = option.model_copy(
                update={
                    "candidates": [
                        candidate.model_copy(update={"model_selection": selected}),
                        *option.candidates[1:],
                    ]
                }
            )
        options[0] = option
        return agent.model_copy(update={"selectable_model_options": options})

    monkeypatch.setattr(fixture.repository.agent_repository, "lock_by_id", changed_lock)
    before = await model_rows(fixture)
    result = await fixture.repository.prepare_fresh(
        agent_id=fixture.agent_id,
        session_id=fixture.session_id,
        run_id=fixture.run_id,
        owner_generation=fixture.generation,
        selected=RequestedProfileSelection(
            agent_default_inference_profile(frame.agent),
            InferenceProfileSource.AGENT_DEFAULT,
        ),
        override=None,
        replace_operation=False,
        prepared_snapshot=frame,
    )
    assert isinstance(result, Success)
    if change == "metadata":
        assert result.value is not None
    else:
        assert result.value is None
        assert await model_rows(fixture) == before


async def test_compaction_input_drift_is_bounded_before_any_slot_write(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    fixture = await model_fixture(rdb_session_manager, "active-compaction-drift")
    active = fixture.repository.active_capabilities_repository
    assert isinstance(active, ModelActiveCapabilities)
    active.matches = False
    before = await model_rows(fixture)
    with pytest.raises(CanonicalExecutionWorkDriftError, match="compaction"):
        await fixture.repository.prepare_compaction(
            agent_id=fixture.agent_id,
            session_id=fixture.session_id,
            run_id=fixture.run_id,
            owner_generation=fixture.generation,
            workspace_id=fixture.workspace_id,
        )
    assert active.captures == active.revalidations == 3
    assert await model_rows(fixture) == before
    assert "slot" not in fixture.fault.trace


async def test_same_candidate_retry_keeps_capture_new_operation_adopts_change(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    fixture = await model_fixture(rdb_session_manager, "active-retry-capture")
    active = fixture.repository.active_capabilities_repository
    assert isinstance(active, ModelActiveCapabilities)
    active.efforts = ["max"]
    original_profile = RequestedProfileSelection(
        RequestedInferenceProfile(
            model_target_label="default",
            reasoning_effort=ModelReasoningEffort.MAX,
            enabled_execution_options=[],
        ),
        InferenceProfileSource.SPAWN_OVERRIDE,
    )
    first = await fixture.repository.prepare_fresh(
        agent_id=fixture.agent_id,
        session_id=fixture.session_id,
        run_id=fixture.run_id,
        owner_generation=fixture.generation,
        selected=original_profile,
        override=original_profile,
        replace_operation=False,
    )
    assert isinstance(first, Success) and first.value is not None
    foreground = first.value.selection.operation
    compaction = first.value.compaction_selection.operation
    active.efforts = ["xhigh"]
    active.matches = False
    retry = dataclasses.replace(
        original_profile, source=InferenceProfileSource.RETRY_ORIGINAL
    )
    reused = await fixture.repository.prepare_fresh(
        agent_id=fixture.agent_id,
        session_id=fixture.session_id,
        run_id=fixture.run_id,
        owner_generation=fixture.generation,
        selected=retry,
        override=retry,
        replace_operation=False,
    )
    assert isinstance(reused, Success) and reused.value is not None
    assert reused.value.selection.operation == foreground
    assert reused.value.compaction_selection.operation == compaction
    assert active.captures == active.revalidations == 1
    active.matches = True
    next_profile = dataclasses.replace(
        retry,
        profile=retry.profile.model_copy(update={"reasoning_effort": None}),
    )
    replacement = await fixture.repository.prepare_fresh(
        agent_id=fixture.agent_id,
        session_id=fixture.session_id,
        run_id=fixture.run_id,
        owner_generation=fixture.generation,
        selected=next_profile,
        override=next_profile,
        replace_operation=True,
    )
    assert isinstance(replacement, Success) and replacement.value is not None
    new_operation = replacement.value.selection.operation
    assert new_operation.operation_id != foreground.operation_id
    assert (
        new_operation.current_candidate.model_selection.normalized_capabilities.reasoning.effort_levels
        == [ModelReasoningEffort.XHIGH]
    )
    assert (
        new_operation.current_candidate.settings
        == foreground.current_candidate.settings
    )
    assert (
        new_operation.current_candidate.model_selection.model_identifier
        == foreground.current_candidate.model_selection.model_identifier
    )
    assert replacement.value.compaction_selection.operation == compaction
    assert active.captures == active.revalidations == 2
