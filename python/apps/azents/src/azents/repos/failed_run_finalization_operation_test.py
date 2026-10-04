"""Real PostgreSQL regressions for Stop-fenced failed Run atomicity."""

import asyncio
import dataclasses
import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from azcommon.uuid import uuid7
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent import SelectableModelCandidate, SelectableModelOption
from azents.core.agent_session_data import AgentSession, AgentSessionCreate
from azents.core.enums import (
    AgentRunParentResultDeliveryState,
    AgentRunStatus,
    AgentSessionProductMode,
    EventKind,
)
from azents.core.inference_profile import RequestedInferenceProfile
from azents.core.model_operation import (
    ModelOperationCandidateOutcomeReason,
    ModelOperationChainExhaustedError,
    ModelOperationKind,
    ModelOperationSnapshot,
    ModelOperationState,
    build_model_operation,
    mark_current_candidate_active,
    mark_current_candidate_quota_and_advance,
)
from azents.engine.events.types import (
    AgentRunState,
    Event,
    RunMarkerPayload,
    SystemErrorPayload,
)
from azents.engine.run.failure import FailedRunAttempt, FailedRunRetryState
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import AgentRunCreate, AgentRunPatch, EventCreate
from azents.repos.agent_mailbox import AgentMailboxRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.repository_test import _create_agent, _create_workspace
from azents.repos.failed_run_finalization_operation import (
    FailedRunFinalization,
    FailedRunFinalizationOperationRepository,
)
from azents.repos.mailbox import MailboxRepository
from azents.repos.mailbox.admission import MailboxAdmissionRepository
from azents.repos.session_execution import CanonicalExecutionOwnerGenerationStaleError
from azents.repos.terminal_finalization import TerminalRunFinalizationRepository
from azents.repos.terminal_finalization_data import (
    TerminalDeliveryDisposition,
    TerminalFinalizationOutcome,
)
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_model_settings,
)


class _ObservedSessionManager:
    """Observe completion around the actual commit/rollback/close manager."""

    def __init__(self, source: SessionManager[AsyncSession]) -> None:
        self.source = source
        self.active_scopes = 0
        self.committed_scopes = 0
        self.failed_scopes = 0
        self.closed_scopes = 0

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncSession]:
        self.active_scopes += 1
        try:
            async with self.source() as session:
                yield session
        except BaseException:
            self.failed_scopes += 1
            raise
        else:
            self.committed_scopes += 1
        finally:
            self.active_scopes -= 1
            self.closed_scopes += 1


class _Sessions(AgentSessionRepository):
    def __init__(self, trace: list[str]) -> None:
        self.trace = trace

    async def wait_for_execution_lock_by_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> AgentSession | None:
        self.trace.append("owner")
        return await super().wait_for_execution_lock_by_id(session, agent_session_id)


class _Transcript(EventTranscriptRepository):
    def __init__(self, trace: list[str]) -> None:
        self.trace = trace

    async def append(self, session: AsyncSession, create: EventCreate) -> Event:
        self.trace.append(create.kind.value)
        return await super().append(session, create)


class _Runs(AgentRunRepository):
    def __init__(self, trace: list[str]) -> None:
        self.trace = trace

    async def mark_terminal_if_running(
        self,
        session: AsyncSession,
        run_id: str,
        status: AgentRunStatus,
        *,
        ended_at: datetime.datetime,
        last_completed_event_id: str | None = None,
        terminal_result_event_id: str | None = None,
        terminal_result_message: str | None = None,
    ) -> AgentRunState | None:
        self.trace.append("mark_terminal_if_running")
        return await super().mark_terminal_if_running(
            session,
            run_id,
            status,
            ended_at=ended_at,
            last_completed_event_id=last_completed_event_id,
            terminal_result_event_id=terminal_result_event_id,
            terminal_result_message=terminal_result_message,
        )


@dataclasses.dataclass(frozen=True)
class _Terminal(TerminalRunFinalizationRepository):
    trace: list[str]
    failure: BaseException | None

    async def lock_run_finalization(
        self,
        session: AsyncSession,
        *,
        run_id: str,
    ) -> None:
        self.trace.append("terminal_prelock")
        await super().lock_run_finalization(session, run_id=run_id)

    async def finalize_run_in_session(
        self,
        session: AsyncSession,
        *,
        run_id: str,
    ) -> TerminalFinalizationOutcome:
        self.trace.append("parent_delivery")
        result = await super().finalize_run_in_session(session, run_id=run_id)
        if self.failure is not None:
            assert result.disposition is TerminalDeliveryDisposition.ENQUEUED
            self.trace.append("delivery_enqueued_before_failure")
            raise self.failure
        return result


@dataclasses.dataclass(frozen=True)
class _Fixture:
    repository: FailedRunFinalizationOperationRepository
    input: FailedRunFinalization
    manager: _ObservedSessionManager
    parent_session_id: str
    parent_session_agent_id: str
    source_session_agent_id: str
    trace: list[str]


def _retry_state() -> FailedRunRetryState:
    now = datetime.datetime.now(datetime.UTC)
    return FailedRunRetryState.from_attempt(
        FailedRunAttempt(
            user_message="temporary failure",
            internal_message="internal provider diagnostic that must not escape",
            error_type="RuntimeError",
            source="engine",
            visibility="internal",
            attempt_number=3,
            occurred_at=now,
        ),
        max_retries=10,
        backoff_seconds=4,
        next_retry_at=now + datetime.timedelta(seconds=4),
    )


async def _fixture(
    source: SessionManager[AsyncSession],
    *,
    terminal_failure: BaseException | None,
) -> _Fixture:
    sessions = AgentSessionRepository()
    async with source() as session:
        slug = f"failed-finalization-{uuid7().hex}"
        workspace_id = await _create_workspace(session, slug)
        agent_id = await _create_agent(session, workspace_id, slug)
        parent_session = await sessions.create(
            session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
            ),
        )
        parent = await sessions.get_session_agent_by_session_id(
            session, parent_session.id
        )
        assert parent is not None
        child = await sessions.create_child_session_agent(
            session,
            parent_session_agent_id=parent.id,
            name="child",
            agent_type="default",
            title=None,
            last_task_message=None,
        )
        generation = await sessions.claim_owner_generation(
            session, child.agent_session_id
        )
        run = await AgentRunRepository().create(
            session,
            AgentRunCreate(
                session_id=child.agent_session_id,
                parent_agent_run_id=None,
                scheduled_task_cycle_id=None,
            ),
        )
    trace: list[str] = []
    manager = _ObservedSessionManager(source)
    tracked_sessions = _Sessions(trace)
    tracked_runs = _Runs(trace)
    terminal = _Terminal(
        session_manager=manager,
        agent_session_repository=tracked_sessions,
        agent_run_repository=tracked_runs,
        agent_mailbox_repository=AgentMailboxRepository(
            mailbox_admission_repository=MailboxAdmissionRepository(
                session_manager=manager,
                mailbox_item_repository=MailboxRepository(),
                agent_session_repository=tracked_sessions,
            ),
            agent_session_repository=tracked_sessions,
        ),
        trace=trace,
        failure=terminal_failure,
    )
    return _Fixture(
        repository=FailedRunFinalizationOperationRepository(
            session_manager=manager,
            agent_session_repository=tracked_sessions,
            transcript_repository=_Transcript(trace),
            run_repository=tracked_runs,
            terminal_finalization_repository=terminal,
        ),
        input=FailedRunFinalization(
            session_id=child.agent_session_id,
            owner_generation=generation,
            run_id=run.id,
            user_message="temporary failure",
            retry_state=_retry_state(),
            reason="retry_exhausted",
            action_hint="try again later",
        ),
        manager=manager,
        parent_session_id=parent_session.id,
        parent_session_agent_id=parent.id,
        source_session_agent_id=child.id,
        trace=trace,
    )


def _terminal_operation(kind: ModelOperationKind) -> ModelOperationSnapshot:
    now = datetime.datetime.now(datetime.UTC)
    operation = build_model_operation(
        option=SelectableModelOption(
            label="default",
            candidates=[
                SelectableModelCandidate(
                    model_selection=make_test_model_selection(),
                    settings=make_test_model_settings(),
                )
            ],
            subagent_enabled=True,
            subagent_guidance=None,
        ),
        profile=RequestedInferenceProfile(
            model_target_label="default",
            reasoning_effort=None,
            enabled_execution_options=[],
        ),
        kind=kind,
        operation_id=uuid7().hex,
        recorded_at=now,
    )
    active = mark_current_candidate_active(
        operation,
        reason=ModelOperationCandidateOutcomeReason.SELECTED,
        recorded_at=now,
    )
    with pytest.raises(ModelOperationChainExhaustedError) as exhausted:
        mark_current_candidate_quota_and_advance(active, recorded_at=now)
    return exhausted.value.operation


async def _assert_no_failure_writes(
    source: SessionManager[AsyncSession],
    fixture: _Fixture,
) -> None:
    async with source() as session:
        run = await AgentRunRepository().get_by_id(session, fixture.input.run_id)
        assert run is not None
        assert run.status is AgentRunStatus.RUNNING
        assert run.parent_result_delivery_state is None
        assert run.terminal_result_event_id is None
        assert (
            await EventTranscriptRepository().list_for_model_input(
                session,
                fixture.input.session_id,
            )
            == []
        )
        assert (
            await MailboxRepository().list_by_session_id(
                session,
                fixture.parent_session_id,
            )
            == []
        )
        sessions = AgentSessionRepository()
        for session_agent_id in (
            fixture.source_session_agent_id,
            fixture.parent_session_agent_id,
        ):
            agent = await sessions.get_session_agent_by_id(session, session_agent_id)
            assert agent is not None
            assert agent.last_message_at is None
    assert fixture.manager.active_scopes == 0


async def test_failed_run_finalization_appends_events_delivery_and_closes(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Original failure metadata and parent delivery commit in the fenced order."""
    fixture = await _fixture(rdb_session_manager, terminal_failure=None)
    result = await fixture.repository.finalize(fixture.input)
    assert result is not None
    assert fixture.trace[:6] == [
        "owner",
        "terminal_prelock",
        EventKind.SYSTEM_ERROR.value,
        EventKind.RUN_MARKER.value,
        "mark_terminal_if_running",
        "parent_delivery",
    ]
    assert (
        result.error_event.external_id
        == f"failed-run:{fixture.input.run_id}:system-error"
    )
    assert (
        result.run_marker.external_id == f"failed-run:{fixture.input.run_id}:run-marker"
    )
    payload = result.error_event.payload
    assert isinstance(payload, SystemErrorPayload)
    assert payload.content == "temporary failure"
    assert payload.failure is not None
    assert payload.failure.finalization_reason == "retry_exhausted"
    assert payload.failure.action_hint == "try again later"
    assert len(payload.failure.attempts) == 1
    assert payload.failure.attempts[0].user_message == "temporary failure"
    assert "internal provider diagnostic" not in payload.model_dump_json()
    marker = result.run_marker.payload
    assert isinstance(marker, RunMarkerPayload)
    assert marker.status == "failed"
    assert marker.error == "temporary failure"
    assert fixture.manager.active_scopes == 0
    assert fixture.manager.committed_scopes == 1
    assert fixture.manager.closed_scopes == 1
    async with rdb_session_manager() as session:
        run = await AgentRunRepository().get_by_id(session, fixture.input.run_id)
        assert run is not None
        assert run.status is AgentRunStatus.FAILED
        assert run.last_completed_event_id == result.run_marker.id
        assert run.terminal_result_event_id == result.error_event.id
        assert run.terminal_result_message == fixture.input.user_message
        assert (
            run.parent_result_delivery_state
            is AgentRunParentResultDeliveryState.ENQUEUED
        )
        [mailbox_item] = await MailboxRepository().list_by_session_id(
            session,
            fixture.parent_session_id,
        )
        assert mailbox_item.id == run.parent_result_mailbox_item_id
        assert mailbox_item.idempotency_key == f"agent_result:{fixture.input.run_id}"
        for session_agent_id in (
            fixture.source_session_agent_id,
            fixture.parent_session_agent_id,
        ):
            agent = await AgentSessionRepository().get_session_agent_by_id(
                session,
                session_agent_id,
            )
            assert agent is not None
            assert agent.last_message_at is not None


async def test_failed_run_finalization_retains_terminal_candidate_outcomes(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Chain exhaustion evidence survives terminal operation-state clearing."""
    fixture = await _fixture(rdb_session_manager, terminal_failure=None)
    operation = _terminal_operation(ModelOperationKind.FOREGROUND)
    async with rdb_session_manager() as session:
        await AgentRunRepository().update(
            session,
            fixture.input.run_id,
            AgentRunPatch(
                model_operation_state=ModelOperationState(
                    foreground=operation,
                    compaction=None,
                )
            ),
        )
    result = await fixture.repository.finalize(
        dataclasses.replace(
            fixture.input,
            user_message="All model candidates are unavailable.",
            reason="non_retryable",
        )
    )
    assert result is not None
    payload = result.error_event.payload
    assert isinstance(payload, SystemErrorPayload)
    assert payload.failure is not None
    assert payload.failure.model_operation is not None
    assert payload.failure.model_operation.operation_id == operation.operation_id
    assert payload.failure.model_operation.terminal_reason.value == "chain_exhausted"
    assert (
        payload.failure.model_operation.outcomes[0].status.value == "quota_or_billing"
    )
    async with rdb_session_manager() as session:
        run = await AgentRunRepository().get_by_id(session, fixture.input.run_id)
        assert run is not None
        assert run.model_operation_state is None


async def test_failed_run_finalization_yields_to_locked_stop_request(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """The removed lifecycle claim regression now covers the completed operation."""
    fixture = await _fixture(rdb_session_manager, terminal_failure=None)
    async with rdb_session_manager() as session:
        sessions = AgentSessionRepository()
        await sessions.mark_running(session, fixture.input.session_id)
        stopped = await sessions.request_stop(
            session,
            session_id=fixture.input.session_id,
            stop_request_id=uuid7().hex,
            stop_requester_user_id=None,
        )
        assert stopped is not None
    assert await fixture.repository.finalize(fixture.input) is None
    assert fixture.trace == ["owner"]
    assert fixture.manager.committed_scopes == 1
    assert fixture.manager.closed_scopes == 1
    await _assert_no_failure_writes(rdb_session_manager, fixture)


async def test_stale_owner_fails_before_event_or_terminal_mutation(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await _fixture(rdb_session_manager, terminal_failure=None)
    async with rdb_session_manager() as session:
        newer_generation = await AgentSessionRepository().claim_owner_generation(
            session,
            fixture.input.session_id,
        )
    assert newer_generation == fixture.input.owner_generation + 1
    with pytest.raises(
        CanonicalExecutionOwnerGenerationStaleError,
        match="Session owner generation is stale",
    ):
        await fixture.repository.finalize(fixture.input)
    assert fixture.trace == ["owner"]
    assert fixture.manager.failed_scopes == 1
    await _assert_no_failure_writes(rdb_session_manager, fixture)


async def test_missing_owned_session_keeps_value_error_semantics(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await _fixture(rdb_session_manager, terminal_failure=None)
    with pytest.raises(ValueError, match="AgentSession not found"):
        await fixture.repository.finalize(
            dataclasses.replace(
                fixture.input,
                session_id=uuid7().hex,
            )
        )
    assert fixture.trace == ["owner"]
    await _assert_no_failure_writes(rdb_session_manager, fixture)


async def test_missing_run_retains_existing_conditional_transition_behavior(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A missing Run retains the original Event append and ineligible delivery."""
    fixture = await _fixture(rdb_session_manager, terminal_failure=None)
    missing_run_id = uuid7().hex
    result = await fixture.repository.finalize(
        dataclasses.replace(fixture.input, run_id=missing_run_id),
    )
    assert result is not None
    assert result.error_event.external_id == f"failed-run:{missing_run_id}:system-error"
    assert fixture.manager.committed_scopes == 1
    assert fixture.manager.active_scopes == 0
    async with rdb_session_manager() as session:
        assert await AgentRunRepository().get_by_id(session, missing_run_id) is None
        original = await AgentRunRepository().get_by_id(session, fixture.input.run_id)
        assert original is not None
        assert original.status is AgentRunStatus.RUNNING
        assert original.parent_result_delivery_state is None
        assert (
            await MailboxRepository().list_by_session_id(
                session,
                fixture.parent_session_id,
            )
            == []
        )


async def test_multiple_terminal_operation_slots_abort_before_failure_events(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await _fixture(rdb_session_manager, terminal_failure=None)
    async with rdb_session_manager() as session:
        await AgentRunRepository().update(
            session,
            fixture.input.run_id,
            AgentRunPatch(
                model_operation_state=ModelOperationState(
                    foreground=_terminal_operation(ModelOperationKind.FOREGROUND),
                    compaction=_terminal_operation(ModelOperationKind.COMPACTION),
                )
            ),
        )
    with pytest.raises(
        RuntimeError, match="Failed Run has multiple terminal model operations"
    ):
        await fixture.repository.finalize(fixture.input)
    assert fixture.trace == ["owner", "terminal_prelock"]
    await _assert_no_failure_writes(rdb_session_manager, fixture)


@pytest.mark.parametrize("cancelled", [False, True])
async def test_terminal_delivery_failure_rolls_back_entire_atomic_group(
    rdb_session_manager: SessionManager[AsyncSession],
    cancelled: bool,
) -> None:
    """Real delivery/activity and all failure Events disappear on abort."""
    failure = asyncio.CancelledError() if cancelled else RuntimeError("delivery failed")
    fixture = await _fixture(rdb_session_manager, terminal_failure=failure)
    expected = asyncio.CancelledError if cancelled else RuntimeError
    with pytest.raises(expected):
        await fixture.repository.finalize(fixture.input)
    assert "delivery_enqueued_before_failure" in fixture.trace
    assert fixture.manager.failed_scopes == 1
    assert fixture.manager.closed_scopes == 1
    await _assert_no_failure_writes(rdb_session_manager, fixture)


async def test_failed_run_replay_keeps_deterministic_events_and_parent_result(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await _fixture(rdb_session_manager, terminal_failure=None)
    first = await fixture.repository.finalize(fixture.input)
    second = await fixture.repository.finalize(fixture.input)
    assert first is not None and second is not None
    assert second.error_event.id == first.error_event.id
    assert second.run_marker.id == first.run_marker.id
    assert fixture.manager.committed_scopes == 2
    assert fixture.manager.active_scopes == 0
    async with rdb_session_manager() as session:
        events = await EventTranscriptRepository().list_for_model_input(
            session,
            fixture.input.session_id,
        )
        assert [event.kind for event in events] == [
            EventKind.SYSTEM_ERROR,
            EventKind.RUN_MARKER,
        ]
        assert (
            len(
                await MailboxRepository().list_by_session_id(
                    session,
                    fixture.parent_session_id,
                )
            )
            == 1
        )


async def test_already_terminal_run_is_not_overwritten_by_failure_transition(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await _fixture(rdb_session_manager, terminal_failure=None)
    async with rdb_session_manager() as session:
        await AgentRunRepository().mark_terminal(
            session,
            fixture.input.run_id,
            AgentRunStatus.STOPPED,
            ended_at=datetime.datetime.now(datetime.UTC),
        )
    result = await fixture.repository.finalize(fixture.input)
    assert result is not None
    async with rdb_session_manager() as session:
        run = await AgentRunRepository().get_by_id(session, fixture.input.run_id)
        assert run is not None
        assert run.status is AgentRunStatus.STOPPED
        [mailbox_item] = await MailboxRepository().list_by_session_id(
            session,
            fixture.parent_session_id,
        )
        assert mailbox_item.content == "The agent run was stopped."
