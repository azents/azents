"""Real PostgreSQL User Stop stage guards, idempotency and rollback tests."""

import asyncio
import dataclasses
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Literal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent_session_data import AgentSessionCreate
from azents.core.enums import (
    AgentRunPhase,
    AgentRunStatus,
    AgentSessionProductMode,
    EventKind,
)
from azents.engine.events.types import (
    ActiveToolCall,
    AssistantMessagePayload,
    ClientToolCallPayload,
    ClientToolResultPayload,
    Event,
    NativeArtifact,
    ReasoningPayload,
)
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import AgentRunCreate, EventCreate
from azents.repos.agent_mailbox import AgentMailboxRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.repository_test import _create_agent, _create_workspace
from azents.repos.engine_tool_result_operation import (
    EngineToolResultOperationRepository,
)
from azents.repos.mailbox import MailboxRepository
from azents.repos.mailbox.admission import MailboxAdmissionRepository
from azents.repos.session_execution import CanonicalExecutionOwnerGenerationStaleError
from azents.repos.terminal_finalization import TerminalRunFinalizationRepository
from azents.repos.user_stop import UserStopOperationRepository
from azents.repos.user_stop_data import (
    UserStopCancelledCallsInput,
    UserStopMarkerInput,
    UserStopOwnerInput,
    UserStopPartialInput,
)
from azents.repos.worker_session import WorkerSessionOperationRepository


class ObservedStopManager:
    """Observe genuine transaction completion, including failed Stop stages."""

    def __init__(self, manager: SessionManager[AsyncSession]) -> None:
        self.manager = manager
        self.active = False
        self.sessions: list[AsyncSession] = []
        self.resolved: list[bool] = []

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncSession]:
        assert not self.active, (
            "A completed operation was nested inside the Stop transaction"
        )
        self.active = True
        current: AsyncSession | None = None
        try:
            async with self.manager() as session:
                current = session
                self.sessions.append(session)
                yield session
        finally:
            self.active = False
            if current is not None:
                self.resolved.append(not current.in_transaction())

    def assert_closed(self) -> None:
        assert not self.active
        assert all(self.resolved)
        assert all(not session.in_transaction() for session in self.sessions)


@dataclasses.dataclass(frozen=True)
class _ObservedWorker(WorkerSessionOperationRepository):
    guard_sessions: list[AsyncSession] = dataclasses.field(
        default_factory=list, init=False
    )

    async def assert_owner_generation_in_session(
        self, session: AsyncSession, *, session_id: str, owner_generation: int
    ) -> None:
        self.guard_sessions.append(session)
        await super().assert_owner_generation_in_session(
            session, session_id=session_id, owner_generation=owner_generation
        )


@dataclasses.dataclass(frozen=True)
class StopFixture:
    owner: UserStopOwnerInput
    run_id: str
    parent_session_id: str | None
    calls: tuple[ActiveToolCall, ...]
    manager: ObservedStopManager
    sessions: AgentSessionRepository
    runs: AgentRunRepository
    transcripts: EventTranscriptRepository
    worker: WorkerSessionOperationRepository
    stop: UserStopOperationRepository


async def stop_fixture(
    manager: SessionManager[AsyncSession], name: str, *, child: bool
) -> StopFixture:
    observed = ObservedStopManager(manager)
    sessions = AgentSessionRepository()
    runs = AgentRunRepository()
    transcripts = EventTranscriptRepository()
    mailbox = MailboxRepository()
    terminal = TerminalRunFinalizationRepository(
        observed,
        runs,
        sessions,
        AgentMailboxRepository(
            MailboxAdmissionRepository(observed, mailbox, sessions), sessions
        ),
    )
    worker = _ObservedWorker(observed, sessions, runs, mailbox, terminal)
    async with manager() as session:
        workspace_id = await _create_workspace(session, name)
        agent_id = await _create_agent(session, workspace_id, name)
        root = await sessions.create(
            session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                title=None,
            ),
        )
        parent_id: str | None = None
        session_id = root.id
        if child:
            parent = await sessions.get_session_agent_by_session_id(session, root.id)
            assert parent is not None
            node = await sessions.create_child_session_agent(
                session,
                parent_session_agent_id=parent.id,
                name="stop-child",
                agent_type="default",
                title=None,
                last_task_message=None,
            )
            parent_id = root.id
            session_id = node.agent_session_id
        generation = await sessions.claim_owner_generation(session, session_id)
        await sessions.mark_running(session, session_id)
        run = await runs.create(
            session,
            AgentRunCreate(
                session_id=session_id,
                parent_agent_run_id=None,
                scheduled_task_cycle_id=None,
                phase=AgentRunPhase.EXECUTING_TOOLS,
                status=AgentRunStatus.RUNNING,
            ),
        )
        calls = (
            ActiveToolCall(
                call_id="call-1",
                name="bash",
                arguments="{}",
                wire_dialect="json_function",
                started_at=datetime.now(UTC),
                owner_generation=generation,
            ),
        )
        await runs.update_phase(
            session,
            run.id,
            AgentRunPhase.EXECUTING_TOOLS,
            active_tool_calls=list(calls),
        )
        await sessions.request_stop(
            session,
            session_id=session_id,
            stop_request_id="stop-request",
            stop_requester_user_id=None,
        )
    stop = UserStopOperationRepository(
        observed,
        worker,
        sessions,
        transcripts,
        EngineToolResultOperationRepository(observed, runs, transcripts),
    )
    return StopFixture(
        UserStopOwnerInput(session_id=session_id, owner_generation=generation),
        run.id,
        parent_id,
        calls,
        observed,
        sessions,
        runs,
        transcripts,
        worker,
        stop,
    )


def native_artifact() -> NativeArtifact:
    return NativeArtifact(
        compat_key="azents-live:live_projection:azents:live:1",
        adapter="azents-live",
        native_format="live_projection",
        provider="azents",
        model="live",
        schema_version="1",
        item={"live_projection": "stop-test"},
    )


def partial(session_id: str, id: str) -> Event:
    return Event(
        id=id,
        session_id=session_id,
        kind=EventKind.ASSISTANT_MESSAGE,
        payload=AssistantMessagePayload(
            content="partial", attachments=[], native_artifact=native_artifact()
        ),
        adapter="azents-live",
        provider="azents",
        model="live",
        native_format="live_projection",
        schema_version="1",
        created_at=datetime.now(UTC),
    )


def live_tool(session_id: str) -> Event:
    return Event(
        id="b" * 32,
        session_id=session_id,
        kind=EventKind.CLIENT_TOOL_CALL,
        payload=ClientToolCallPayload(
            call_id="redis-only",
            name="bash",
            arguments="{}",
            native_artifact=native_artifact(),
            wire_dialect="json_function",
        ),
        created_at=datetime.now(UTC),
    )


async def history(fixture: StopFixture) -> list[Event]:
    async with fixture.manager.manager() as session:
        return await fixture.transcripts.list_recent_by_session_id(
            session, fixture.owner.session_id, limit=100
        )


class FaultTranscript(EventTranscriptRepository):
    """Fail after a specified genuine transcript write, without a DB callback."""

    def __init__(self, kind: EventKind, ordinal: int, error: BaseException) -> None:
        self.kind = kind
        self.ordinal = ordinal
        self.error = error
        self.writes: list[EventCreate] = []

    async def append(self, session: AsyncSession, create: EventCreate) -> Event:
        result = await super().append(session, create)
        self.writes.append(create)
        if (
            create.kind is self.kind
            and sum(write.kind is self.kind for write in self.writes) == self.ordinal
        ):
            raise self.error
        return result


class FaultClear(AgentSessionRepository):
    """Fail after the real Stop request mutation to exercise rollback."""

    def __init__(self, error: BaseException) -> None:
        self.error = error

    async def clear_stop_request(self, session: AsyncSession, session_id: str) -> None:
        await super().clear_stop_request(session, session_id=session_id)
        raise self.error


def fault_stop(
    fixture: StopFixture, transcript: EventTranscriptRepository
) -> UserStopOperationRepository:
    return dataclasses.replace(
        fixture.stop,
        event_transcript_repository=transcript,
        tool_result_repository=EngineToolResultOperationRepository(
            fixture.manager, fixture.runs, transcript
        ),
    )


async def test_partial_eligibility_metadata_and_repeat_are_guarded_and_idempotent(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await stop_fixture(
        rdb_session_manager, "stop-partial-repeat", child=False
    )
    assistant = partial(fixture.owner.session_id, "a" * 32)
    reasoning = Event(
        id="e" * 32,
        session_id=fixture.owner.session_id,
        kind=EventKind.REASONING,
        payload=ReasoningPayload(
            summary="partial thought", native_artifact=native_artifact()
        ),
        created_at=datetime.now(UTC),
    )
    input = UserStopPartialInput(
        session_id=fixture.owner.session_id,
        owner_generation=fixture.owner.owner_generation,
        events=(assistant, live_tool(fixture.owner.session_id), reasoning),
    )
    await fixture.stop.append_partial_events(input)
    await fixture.stop.append_partial_events(input)
    events = await history(fixture)
    assert [event.external_id for event in events] == [assistant.id, reasoning.id]
    assert events[0].adapter == assistant.adapter
    assert events[0].provider == assistant.provider
    assert events[0].model == assistant.model
    assert events[0].native_format == assistant.native_format
    assert events[0].schema_version == assistant.schema_version
    assert events[0].payload == assistant.payload
    fixture.manager.assert_closed()
    assert len(fixture.manager.sessions) == 2


async def test_cancelled_calls_deduplicate_in_same_tool_result_transaction(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await stop_fixture(rdb_session_manager, "stop-cancel-repeat", child=False)
    call = fixture.calls[0]
    duplicate = call.model_copy(update={"name": "last-admitted-name"})
    input = UserStopCancelledCallsInput(
        session_id=fixture.owner.session_id,
        owner_generation=fixture.owner.owner_generation,
        run_id=fixture.run_id,
        active_tool_calls=(call, duplicate),
    )
    await fixture.stop.append_cancelled_tool_results(input)
    await fixture.stop.append_cancelled_tool_results(input)
    events = await history(fixture)
    assert len(events) == 1
    assert events[0].external_id == f"tool-result:{fixture.run_id}:{call.call_id}"
    assert isinstance(events[0].payload, ClientToolResultPayload)
    assert events[0].payload.status == "cancelled"
    assert events[0].payload.name == "last-admitted-name"
    async with rdb_session_manager() as session:
        run = await fixture.runs.get_by_id(session, fixture.run_id)
        assert run is not None and run.active_tool_calls == []
        assert run.phase is AgentRunPhase.APPENDING_EVENTS
    fixture.manager.assert_closed()
    assert len(fixture.manager.sessions) == 2


async def test_empty_actions_skip_factories_and_missing_run_keeps_runtime_error(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await stop_fixture(rdb_session_manager, "stop-empty-actions", child=False)
    await fixture.stop.append_partial_events(
        UserStopPartialInput(
            session_id=fixture.owner.session_id,
            owner_generation=fixture.owner.owner_generation,
            events=(live_tool(fixture.owner.session_id),),
        )
    )
    await fixture.stop.append_cancelled_tool_results(
        UserStopCancelledCallsInput(
            session_id=fixture.owner.session_id,
            owner_generation=fixture.owner.owner_generation,
            run_id=None,
            active_tool_calls=(),
        )
    )
    with pytest.raises(
        RuntimeError, match="Active tool calls require a running AgentRun"
    ):
        await fixture.stop.append_cancelled_tool_results(
            UserStopCancelledCallsInput(
                session_id=fixture.owner.session_id,
                owner_generation=fixture.owner.owner_generation,
                run_id=None,
                active_tool_calls=fixture.calls,
            )
        )
    assert fixture.manager.sessions == []
    assert await history(fixture) == []


Action = Literal["partial", "cancelled", "markers", "clear"]


async def perform_action(
    fixture: StopFixture,
    stop: UserStopOperationRepository,
    action: Action,
    owner: UserStopOwnerInput,
) -> None:
    if action == "partial":
        await stop.append_partial_events(
            UserStopPartialInput(
                session_id=owner.session_id,
                owner_generation=owner.owner_generation,
                events=(partial(owner.session_id, "a" * 32),),
            )
        )
    elif action == "cancelled":
        await stop.append_cancelled_tool_results(
            UserStopCancelledCallsInput(
                session_id=owner.session_id,
                owner_generation=owner.owner_generation,
                run_id=fixture.run_id,
                active_tool_calls=fixture.calls,
            )
        )
    elif action == "markers":
        await stop.append_user_stop_events(
            UserStopMarkerInput(
                session_id=owner.session_id,
                owner_generation=owner.owner_generation,
                run_id=fixture.run_id,
            )
        )
    else:
        await stop.clear_stop_request(owner)


@pytest.mark.parametrize("action", ["partial", "cancelled", "markers", "clear"])
@pytest.mark.parametrize("missing", [False, True])
async def test_all_four_actions_keep_guard_missing_vs_stale_before_writes(
    rdb_session_manager: SessionManager[AsyncSession], action: Action, missing: bool
) -> None:
    fixture = await stop_fixture(
        rdb_session_manager, f"stop-guard-{action}-{missing}", child=False
    )
    owner = UserStopOwnerInput(
        session_id="0" * 32 if missing else fixture.owner.session_id,
        owner_generation=fixture.owner.owner_generation + 1,
    )
    expected = ValueError if missing else CanonicalExecutionOwnerGenerationStaleError
    with pytest.raises(
        expected,
        match="AgentSession not found"
        if missing
        else "Session owner generation is stale",
    ):
        await perform_action(fixture, fixture.stop, action, owner)
    assert await history(fixture) == []
    async with rdb_session_manager() as session:
        assert await fixture.sessions.has_stop_request(
            session, fixture.owner.session_id
        )
        run = await fixture.runs.get_by_id(session, fixture.run_id)
        assert run is not None and tuple(run.active_tool_calls) == fixture.calls
    fixture.manager.assert_closed()


async def test_missing_run_rolls_back_result_append_but_preserves_prior_partial_commit(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await stop_fixture(rdb_session_manager, "stop-missing-run", child=False)
    event = partial(fixture.owner.session_id, "a" * 32)
    await fixture.stop.append_partial_events(
        UserStopPartialInput(
            session_id=fixture.owner.session_id,
            owner_generation=fixture.owner.owner_generation,
            events=(event,),
        )
    )
    with pytest.raises(ValueError, match="Agent run not found"):
        await fixture.stop.append_cancelled_tool_results(
            UserStopCancelledCallsInput(
                session_id=fixture.owner.session_id,
                owner_generation=fixture.owner.owner_generation,
                run_id="0" * 32,
                active_tool_calls=fixture.calls,
            )
        )
    assert [item.external_id for item in await history(fixture)] == [event.id]
    fixture.manager.assert_closed()


@pytest.mark.parametrize("action", ["partial", "cancelled", "markers", "clear"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_stage_write_failure_or_cancellation_rolls_back_only_that_stage(
    rdb_session_manager: SessionManager[AsyncSession], action: Action, cancel: bool
) -> None:
    fixture = await stop_fixture(
        rdb_session_manager, f"stop-failure-{action}-{cancel}", child=False
    )
    error = (
        asyncio.CancelledError()
        if cancel
        else RuntimeError("stage failure after write")
    )
    if action == "clear":
        stop = dataclasses.replace(
            fixture.stop, agent_session_repository=FaultClear(error)
        )
    else:
        target_kind = {
            "partial": EventKind.ASSISTANT_MESSAGE,
            "cancelled": EventKind.CLIENT_TOOL_RESULT,
            "markers": EventKind.RUN_MARKER,
        }[action]
        stop = fault_stop(fixture, FaultTranscript(target_kind, 1, error))
    with pytest.raises(type(error)):
        await perform_action(fixture, stop, action, fixture.owner)
    assert await history(fixture) == []
    async with rdb_session_manager() as session:
        assert await fixture.sessions.has_stop_request(
            session, fixture.owner.session_id
        )
        run = await fixture.runs.get_by_id(session, fixture.run_id)
        assert run is not None and tuple(run.active_tool_calls) == fixture.calls
    fixture.manager.assert_closed()


async def test_interrupted_marker_pair_is_idempotent_in_one_guarded_stage(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await stop_fixture(rdb_session_manager, "stop-marker-repeat", child=False)
    input = UserStopMarkerInput(
        session_id=fixture.owner.session_id,
        owner_generation=fixture.owner.owner_generation,
        run_id=fixture.run_id,
    )
    first = await fixture.stop.append_user_stop_events(input)
    repeated = await fixture.stop.append_user_stop_events(input)
    assert first == repeated
    assert [event.external_id for event in await history(fixture)] == [
        f"interrupted:{fixture.run_id}:user_requested",
        f"run-marker:{fixture.run_id}:interrupted",
    ]
    assert len(fixture.manager.sessions) == 2
    fixture.manager.assert_closed()


class _PausedTranscript(EventTranscriptRepository):
    def __init__(self) -> None:
        self.written = asyncio.Event()
        self.release = asyncio.Event()

    async def append(self, session: AsyncSession, create: EventCreate) -> Event:
        event = await super().append(session, create)
        self.written.set()
        await self.release.wait()
        return event


async def test_actual_task_cancellation_after_partial_write_abandons_transaction(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await stop_fixture(
        rdb_session_manager, "stop-task-cancellation", child=False
    )
    transcript = _PausedTranscript()
    stop = fault_stop(fixture, transcript)
    task = asyncio.create_task(
        stop.append_partial_events(
            UserStopPartialInput(
                session_id=fixture.owner.session_id,
                owner_generation=fixture.owner.owner_generation,
                events=(partial(fixture.owner.session_id, "a" * 32),),
            )
        )
    )
    try:
        await asyncio.wait_for(transcript.written.wait(), timeout=5)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert task.cancelled()
    assert await history(fixture) == []
    fixture.manager.assert_closed()
