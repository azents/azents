"""Atomic completed Engine model-input operation regression tests."""

import asyncio
import datetime
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Literal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRunPhase,
    AgentRunStatus,
    EventKind,
    ExchangeFileStatus,
    ModelFileStatus,
)
from azents.engine.events.types import (
    ActiveToolCall,
    AgentRunState,
    Attachment,
    ClientToolCallPayload,
    ClientToolResultPayload,
    Event,
    EventPayload,
    FileOutputPart,
    InputTextPart,
    NativeArtifact,
    OutputTextPart,
    UserMessagePayload,
    build_native_compat_key,
    validate_event_payload,
)
from azents.rdb.session_capabilities import ReadSession, ReadWriteSession, WriteSession
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.engine_input_projection import EngineInputProjectionRepository
from azents.repos.engine_model_input_operation import (
    EngineModelInputOperationRepository,
)
from azents.repos.engine_tool_result_operation import (
    EngineToolResultOperationRepository,
)

_NOW = datetime.datetime.now(datetime.UTC)
_RUN_ID = "1" * 32
_SESSION_ID = "2" * 32


@dataclass
class _Database:
    """Shared test persistence rolled back at the operation boundary."""

    run: AgentRunState | None
    events: list[Event]


class _SessionManager:
    """Track one session and emulate commit or atomic rollback."""

    def __init__(self, database: _Database, *, commit_failure: bool) -> None:
        self.database = database
        self.commit_failure = commit_failure
        self.active = False
        self.sessions: list[WriteSession] = []
        self.commit_count = 0
        self.rollback_count = 0
        self.operations: list[str] = []

    def assert_session(self, session: ReadSession) -> None:
        """Require every composed operation to use the one active session."""
        assert self.active
        assert session is self.sessions[-1]

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[WriteSession]:
        """Return input only after commit, restoring all state on any failure."""
        assert not self.active
        saved_run = self.database.run
        saved_events = list(self.database.events)
        session = ReadWriteSession(AsyncSession())
        self.sessions.append(session)
        self.active = True
        try:
            yield session
            if self.commit_failure:
                raise ValueError("commit failed")
            self.commit_count += 1
        except BaseException:
            self.database.run = saved_run
            self.database.events = saved_events
            self.rollback_count += 1
            raise
        finally:
            self.active = False
            await session.write_session.close()


class _RunRepository(AgentRunRepository):
    """Record Run reads, lock order, and atomic phase/active-call changes."""

    def __init__(self, manager: _SessionManager, *, phase_failure: bool) -> None:
        self.manager = manager
        self.phase_failure = phase_failure

    async def get_by_id(
        self, session: ReadSession, run_id: str
    ) -> AgentRunState | None:
        """Read the authoritative detached Run state."""
        self.manager.assert_session(session)
        assert run_id == _RUN_ID
        return self.manager.database.run

    async def lock_by_id(
        self, session: ReadSession, run_id: str
    ) -> AgentRunState | None:
        """Record that result append precedes the Run row lock."""
        self.manager.assert_session(session)
        self.manager.operations.append("lock_run")
        return await self.get_by_id(session, run_id)

    async def update_phase(
        self,
        session: ReadSession,
        run_id: str,
        phase: AgentRunPhase,
        *,
        active_tool_calls: list[ActiveToolCall] | None = None,
    ) -> AgentRunState:
        """Persist phase and active-call changes in the shared DB atomic group."""
        self.manager.assert_session(session)
        if phase is AgentRunPhase.PREPARING_INPUT and self.phase_failure:
            raise ValueError("phase failed")
        self.manager.operations.append(phase.value)
        run = await self.get_by_id(session, run_id)
        assert run is not None
        updated = run.model_copy(
            update={
                "phase": phase,
                "model_call_started_at": None,
                "active_tool_calls": (
                    run.active_tool_calls
                    if active_tool_calls is None
                    else active_tool_calls
                ),
            }
        )
        self.manager.database.run = updated
        return updated


class _TranscriptRepository(EventTranscriptRepository):
    """Persist immutable Events and record selection and projection boundaries."""

    def __init__(self, manager: _SessionManager) -> None:
        self.manager = manager
        self.heads: list[str | None] = []

    async def list_for_model_input(
        self,
        session: ReadSession,
        session_id: str,
        *,
        head_event_id: str | None = None,
    ) -> list[Event]:
        """Capture the same head before and after Tool reconciliation."""
        self.manager.assert_session(session)
        assert session_id == _SESSION_ID
        self.heads.append(head_event_id)
        return [
            event
            for event in self.manager.database.events
            if head_event_id is None or event.id >= head_event_id
        ]

    async def append(self, session: ReadSession, create: EventCreate) -> Event:
        """Idempotently append a recovered Tool result without executing it."""
        self.manager.assert_session(session)
        self.manager.operations.append("append_result")
        for event in self.manager.database.events:
            if event.external_id == create.external_id:
                return event
        next_id = max(int(event.id) for event in self.manager.database.events) + 1
        event = Event(
            id=f"{next_id:032d}",
            session_id=create.session_id,
            kind=create.kind,
            payload=validate_event_payload(create.kind, create.payload),
            external_id=create.external_id,
            created_at=_NOW,
        )
        self.manager.database.events.append(event)
        return event

    async def update_payload(
        self, session: ReadSession, event_id: str, payload: EventPayload
    ) -> Event:
        """Change a durable payload inside the input preparation transaction."""
        self.manager.assert_session(session)
        self.manager.operations.append("update_payload")
        for index, event in enumerate(self.manager.database.events):
            if event.id == event_id:
                updated = event.model_copy(update={"payload": payload})
                self.manager.database.events[index] = updated
                return updated
        raise AssertionError("event not found")


class _SessionHeadRepository:
    """Optional model-input selection head read once in the shared session."""

    def __init__(self, manager: _SessionManager, *, head: str | None) -> None:
        self.manager = manager
        self.model_input_head_event_id = head

    async def get_by_id(
        self, session: ReadSession, session_id: str
    ) -> "_SessionHeadRepository":
        """Read the captured model-input head."""
        self.manager.assert_session(session)
        assert session_id == _SESSION_ID
        self.manager.operations.append("read_head")
        return self


class _ExchangeFileRepository:
    """Observe Exchange projection before ModelFile placeholder preparation."""

    def __init__(self, manager: _SessionManager) -> None:
        self.manager = manager

    async def list_statuses_by_object_key(
        self, session: ReadSession, *, object_keys: Sequence[str]
    ) -> dict[str, ExchangeFileStatus]:
        """Treat the selected Exchange attachment as missing metadata."""
        self.manager.assert_session(session)
        assert object_keys == ["test/object"]
        self.manager.operations.append("exchange_status")
        return {}


class _ModelFileRepository:
    """Observe a later projection failure or cancellation inside the DB group."""

    def __init__(
        self, manager: _SessionManager, *, failure: BaseException | None
    ) -> None:
        self.manager = manager
        self.failure = failure

    async def list_statuses_for_session(
        self,
        session: ReadSession,
        *,
        session_id: str,
        model_file_ids: Sequence[str],
    ) -> dict[str, ModelFileStatus]:
        """Assert earlier repair, phase, and attachment writes are uncommitted."""
        self.manager.assert_session(session)
        assert session_id == _SESSION_ID
        assert model_file_ids == ["m" * 32]
        self.manager.operations.append("model_status")
        assert self.manager.commit_count == 0
        if self.failure is not None:
            raise self.failure
        return {}


@dataclass(frozen=True)
class _TestOperation:
    """Named dependencies and authoritative state for one operation test."""

    repository: EngineModelInputOperationRepository
    manager: _SessionManager
    database: _Database
    transcript: _TranscriptRepository


def _run(*, active_calls: list[ActiveToolCall]) -> AgentRunState:
    """Build the immutable Run snapshot used by focused persistence fakes."""
    return AgentRunState(
        id=_RUN_ID,
        session_id=_SESSION_ID,
        scheduled_task_cycle_id=None,
        run_index=1,
        phase=AgentRunPhase.EXECUTING_TOOLS,
        status=AgentRunStatus.RUNNING,
        parent_agent_run_id=None,
        requested_model_target_label=None,
        requested_reasoning_effort=None,
        requested_enabled_execution_options=[],
        active_tool_calls=active_calls,
        parent_result_delivery_state=None,
        parent_result_mailbox_item_id=None,
        parent_result_enqueued_at=None,
        created_at=_NOW,
        started_at=_NOW,
        model_call_started_at=_NOW,
        terminal_result_event_id=None,
        terminal_result_message=None,
        updated_at=_NOW,
    )


def _active(call_id: str, *, generation: int) -> ActiveToolCall:
    """Create admitted Tool ownership with an explicit execution generation."""
    return ActiveToolCall(
        call_id=call_id,
        name="read",
        arguments="{}",
        started_at=_NOW,
        owner_generation=generation,
        wire_dialect="json_function",
    )


def _event(number: int, kind: EventKind, payload: EventPayload) -> Event:
    """Create one durable Event without external preparation."""
    return Event(
        id=f"{number:032d}",
        session_id=_SESSION_ID,
        kind=kind,
        payload=payload,
        created_at=_NOW,
    )


def _call_event(*, name: str) -> Event:
    """Create one unresolved durable Tool call."""
    return _event(
        20,
        EventKind.CLIENT_TOOL_CALL,
        ClientToolCallPayload(
            call_id="call-1",
            name=name,
            arguments="{}",
            wire_dialect="json_function",
            native_artifact=NativeArtifact(
                compat_key=build_native_compat_key(
                    adapter="test",
                    native_format="responses",
                    provider="test",
                    model="test",
                    schema_version="1",
                ),
                adapter="test",
                native_format="responses",
                provider="test",
                model="test",
                schema_version="1",
                item={"type": "function_call"},
            ),
        ),
    )


def _projection_event() -> Event:
    """Create an Event requiring both ordered availability projections."""
    return _event(
        10,
        EventKind.USER_MESSAGE,
        UserMessagePayload(
            sender_user_id=None,
            content=[
                FileOutputPart(
                    model_file_id="m" * 32,
                    media_type="image/png",
                    name="input.png",
                    size=10,
                    kind="image",
                )
            ],
            attachments=[
                Attachment(
                    attachment_id="attachment-1",
                    uri="exchange://test/object",
                    name="input.txt",
                    media_type="text/plain",
                    size=10,
                    created_at=_NOW,
                )
            ],
        ),
    )


def _operation(
    *,
    run: AgentRunState | None,
    events: list[Event],
    head: str | None,
    failure_at: Literal["phase", "projection", "commit", "cancelled"] | None,
) -> _TestOperation:
    """Compose the real input/projection/result repositories around one DB fake."""
    database = _Database(run=run, events=list(events))
    manager = _SessionManager(database, commit_failure=failure_at == "commit")
    runs = _RunRepository(manager, phase_failure=failure_at == "phase")
    transcript = _TranscriptRepository(manager)
    projection_failure: BaseException | None = None
    if failure_at == "projection":
        projection_failure = ValueError("projection failed")
    elif failure_at == "cancelled":
        projection_failure = asyncio.CancelledError()
    repository = EngineModelInputOperationRepository(
        owner=None,
        session_manager=manager,
        run_repository=runs,
        transcript_repository=transcript,
        session_head_repository=_SessionHeadRepository(manager, head=head),
        tool_result_repository=EngineToolResultOperationRepository(
            owner=None,
            session_manager=manager,
            run_repository=runs,
            transcript_repository=transcript,
        ),
        input_projection_repository=EngineInputProjectionRepository(
            exchange_file_repository=_ExchangeFileRepository(manager),
            model_file_repository=_ModelFileRepository(
                manager, failure=projection_failure
            ),
            transcript_repository=transcript,
        ),
    )
    return _TestOperation(
        repository=repository,
        manager=manager,
        database=database,
        transcript=transcript,
    )


async def test_input_repair_phase_and_projections_commit_once_before_return() -> None:
    """Every input-preparation write uses one session before detached return."""
    state = _operation(
        run=_run(active_calls=[_active("call-1", generation=1)]),
        events=[_projection_event(), _call_event(name="read")],
        head=f"{10:032d}",
        failure_at=None,
    )

    prepared = await state.repository.prepare_input(
        run_id=_RUN_ID, session_id=_SESSION_ID, owner_generation=1
    )

    assert not state.manager.active
    assert state.manager.commit_count == 1
    assert len(state.manager.sessions) == 1
    assert state.manager.rollback_count == 0
    assert state.transcript.heads == [f"{10:032d}", f"{10:032d}"]
    assert prepared.model_call_started_at is None
    assert len(prepared.repaired_events) == 1
    result = prepared.repaired_events[0]
    assert result.external_id == f"tool-result:{_RUN_ID}:call-1"
    payload = result.payload
    assert isinstance(payload, ClientToolResultPayload)
    assert payload.status == "cancelled"
    assert payload.output == [
        OutputTextPart(
            text="Tool execution was cancelled before a result was recorded."
        )
    ]
    projected = prepared.transcript[0].payload
    assert isinstance(projected, UserMessagePayload)
    assert projected.attachments[0].availability == "unavailable"
    assert isinstance(projected.content, list)
    assert isinstance(projected.content[0], InputTextPart)
    assert "model file metadata is unavailable" in projected.content[0].text
    run = state.database.run
    assert run is not None
    assert run.phase is AgentRunPhase.PREPARING_INPUT
    assert run.active_tool_calls == []
    order = state.manager.operations
    assert order.index("append_result") < order.index("lock_run")
    assert order.index("lock_run") < order.index(AgentRunPhase.PREPARING_INPUT.value)
    assert (
        order.index(AgentRunPhase.PREPARING_INPUT.value)
        < order.index("exchange_status")
        < order.index("model_status")
    )


@pytest.mark.parametrize("failure_at", ["phase", "projection", "commit", "cancelled"])
async def test_input_atomic_group_rolls_back_on_late_failure_or_cancellation(
    failure_at: Literal["phase", "projection", "commit", "cancelled"],
) -> None:
    """A later failure restores repair, ownership, phase, and payload together."""
    original_run = _run(active_calls=[_active("call-1", generation=1)])
    original_events = [_projection_event(), _call_event(name="read")]
    state = _operation(
        run=original_run,
        events=original_events,
        head=None,
        failure_at=failure_at,
    )
    expected_error = asyncio.CancelledError if failure_at == "cancelled" else ValueError

    with pytest.raises(expected_error):
        await state.repository.prepare_input(
            run_id=_RUN_ID, session_id=_SESSION_ID, owner_generation=1
        )

    assert not state.manager.active
    assert state.manager.commit_count == 0
    assert state.manager.rollback_count == 1
    assert len(state.manager.sessions) == 1
    assert state.database.run == original_run
    assert state.database.events == original_events
    assert "append_result" in state.manager.operations
    if failure_at != "phase":
        assert "update_payload" in state.manager.operations


@pytest.mark.parametrize("invalid", ["missing_run", "missing_call", "future_owner"])
async def test_input_rejects_invalid_authority_before_any_write(
    invalid: Literal["missing_run", "missing_call", "future_owner"],
) -> None:
    """Validate durable call presence and generation before result repair."""
    run = (
        None
        if invalid == "missing_run"
        else _run(
            active_calls=[
                _active("call-1", generation=2 if invalid == "future_owner" else 1)
            ]
        )
    )
    events = [] if invalid == "missing_call" else [_call_event(name="read")]
    state = _operation(run=run, events=events, head=None, failure_at=None)
    expected_error = ValueError if invalid == "missing_run" else RuntimeError

    with pytest.raises(expected_error):
        await state.repository.prepare_input(
            run_id=_RUN_ID, session_id=_SESSION_ID, owner_generation=1
        )

    assert state.manager.operations == ["read_head"]
    assert state.manager.rollback_count == 1
    assert state.manager.commit_count == 0
    assert not state.manager.active
    assert state.database.run == run
    assert state.database.events == events


async def test_input_reuses_head_and_excludes_older_unresolved_calls() -> None:
    """Repair only calls in the captured current model-input transcript."""
    old_call = _call_event(name="read").model_copy(update={"id": f"{5:032d}"})
    current = _event(
        10,
        EventKind.USER_MESSAGE,
        UserMessagePayload(sender_user_id=None, content="current"),
    )
    state = _operation(
        run=_run(active_calls=[]),
        events=[old_call, current],
        head=current.id,
        failure_at=None,
    )

    prepared = await state.repository.prepare_input(
        run_id=_RUN_ID, session_id=_SESSION_ID, owner_generation=1
    )

    assert prepared.transcript == [current]
    assert prepared.repaired_events == []
    assert state.transcript.heads == [current.id]
    assert "append_result" not in state.manager.operations
    assert state.manager.commit_count == 1


async def test_input_preserves_existing_result_and_removes_stale_active_entry() -> None:
    """Do not replace a resolved result while clearing its stale ownership."""
    result = _event(
        21,
        EventKind.CLIENT_TOOL_RESULT,
        ClientToolResultPayload(
            call_id="call-1",
            name="read",
            wire_dialect="json_function",
            status="completed",
            output=[OutputTextPart(text="original result")],
        ),
    )
    state = _operation(
        run=_run(active_calls=[_active("call-1", generation=1)]),
        events=[_call_event(name="read"), result],
        head=None,
        failure_at=None,
    )

    prepared = await state.repository.prepare_input(
        run_id=_RUN_ID, session_id=_SESSION_ID, owner_generation=2
    )

    assert prepared.repaired_events == []
    assert prepared.transcript[-1] is result
    assert state.database.run is not None
    assert state.database.run.active_tool_calls == []
    assert "append_result" not in state.manager.operations
    assert state.manager.commit_count == 1


async def test_scheduled_terminal_recovery_completes_once_without_replay() -> None:
    """A committed scheduled result is recovered as completed, not cancelled."""
    run = _run(active_calls=[_active("call-1", generation=1)]).model_copy(
        update={
            "scheduled_task_cycle_id": "c" * 32,
            "terminal_result_event_id": "e" * 32,
        }
    )
    state = _operation(
        run=run,
        events=[_call_event(name="submit_scheduled_task_result")],
        head=None,
        failure_at=None,
    )

    prepared = await state.repository.prepare_input(
        run_id=_RUN_ID, session_id=_SESSION_ID, owner_generation=1
    )
    payload = prepared.repaired_events[0].payload
    assert isinstance(payload, ClientToolResultPayload)
    assert payload.status == "completed"
    assert payload.output == [
        OutputTextPart(text="The Scheduled Task result was already committed.")
    ]
    assert state.database.run is not None
    assert state.database.run.active_tool_calls == []
    assert not state.manager.active

    repeated = await state.repository.prepare_input(
        run_id=_RUN_ID, session_id=_SESSION_ID, owner_generation=1
    )

    assert repeated.repaired_events == []
    assert repeated.transcript == prepared.transcript
    assert len(state.database.events) == 2
    assert state.manager.commit_count == 2
