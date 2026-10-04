"""Completed Engine tool-result operation tests."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentRunPhase, AgentRunStatus
from azents.engine.client_tools import ClientToolWireDialect
from azents.engine.events.types import (
    ActiveToolCall,
    ClientToolResultPayload,
    Event,
    validate_event_payload,
)
from azents.rdb.session_capabilities import ReadSession, ReadWriteSession, WriteSession
from azents.repos.agent_execution.data import EventCreate
from azents.repos.engine_tool_result_operation import (
    EngineToolResultOperationRepository,
)


class _Session(AsyncSession):
    """Session tracking successful operation commits."""

    def __init__(self) -> None:
        super().__init__()
        self.commit_count = 0

    async def commit(self) -> None:
        """Record one successful context exit."""
        self.commit_count += 1


class _SessionManager:
    """Expose transaction activity for completed-operation assertions."""

    def __init__(self) -> None:
        self.sessions: list[_Session] = []
        self.active = False

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[WriteSession]:
        """Yield one session and commit only after successful admission."""
        assert not self.active
        session = _Session()
        self.sessions.append(session)
        self.active = True
        try:
            yield ReadWriteSession(session)
        except BaseException:
            raise
        else:
            await session.commit()
        finally:
            self.active = False


@dataclass(frozen=True)
class _Call:
    """Minimal admitted tool-call identity."""

    call_id: str
    name: str
    wire_dialect: ClientToolWireDialect


@dataclass(frozen=True)
class _RunState:
    """Detached Run state used by result admission."""

    status: AgentRunStatus
    active_tool_calls: list[ActiveToolCall]


class _RunRepository:
    """Record Run locks and active-tool updates."""

    def __init__(self, manager: _SessionManager, run: _RunState) -> None:
        self.manager = manager
        self.run = run
        self.updates: list[tuple[AgentRunPhase, list[ActiveToolCall] | None]] = []

    async def lock_by_id(
        self,
        session: ReadSession,
        run_id: str,
    ) -> _RunState:
        """Return the configured locked Run."""
        del run_id
        assert self.manager.active
        assert session.read_session is self.manager.sessions[-1]
        return self.run

    async def update_phase(
        self,
        session: ReadSession,
        run_id: str,
        phase: AgentRunPhase,
        *,
        active_tool_calls: list[ActiveToolCall] | None = None,
    ) -> object:
        """Record the phase selected after result admission."""
        del run_id
        assert self.manager.active
        assert session.read_session is self.manager.sessions[-1]
        self.updates.append((phase, active_tool_calls))
        return object()


class _TranscriptRepository:
    """Record deterministic tool-result append requests."""

    def __init__(self, manager: _SessionManager) -> None:
        self.manager = manager
        self.creates: list[EventCreate] = []

    async def append(self, session: ReadSession, create: EventCreate) -> Event:
        """Append while the operation transaction remains active."""
        assert self.manager.active
        assert session.read_session is self.manager.sessions[-1]
        self.creates.append(create)
        return Event(
            id=f"{len(self.creates):032d}",
            session_id=create.session_id,
            kind=create.kind,
            payload=validate_event_payload(create.kind, create.payload),
            external_id=create.external_id,
            created_at=datetime.datetime.now(datetime.UTC),
        )


def _active(call_id: str) -> ActiveToolCall:
    """Create one active tool ownership entry."""
    return ActiveToolCall(
        call_id=call_id,
        name=f"tool-{call_id}",
        arguments=None,
        wire_dialect="json_function",
        started_at=datetime.datetime.now(datetime.UTC),
        owner_generation=1,
    )


async def test_tool_result_finalization_closes_transaction_before_returning() -> None:
    """Result append and active-call removal commit before returning."""
    manager = _SessionManager()
    runs = _RunRepository(
        manager,
        _RunState(
            status=AgentRunStatus.RUNNING,
            active_tool_calls=[_active("call-1"), _active("call-2")],
        ),
    )
    transcript = _TranscriptRepository(manager)
    repository = EngineToolResultOperationRepository(
        session_manager=manager,
        run_repository=runs,
        transcript_repository=transcript,
    )

    event = await repository.finalize(
        run_id="run-1",
        session_id="session-1",
        call=_Call("call-1", "tool-call-1", "json_function"),
        result=ClientToolResultPayload(
            call_id="call-1",
            name="tool-call-1",
            wire_dialect="json_function",
            status="completed",
            output=[],
        ),
    )

    assert not manager.active
    assert manager.sessions[0].commit_count == 1
    assert event.external_id == "tool-result:run-1:call-1"
    assert len(runs.updates) == 1
    phase, remaining = runs.updates[0]
    assert phase is AgentRunPhase.EXECUTING_TOOLS
    assert remaining is not None
    assert [active.call_id for active in remaining] == ["call-2"]


async def test_terminal_run_result_does_not_rewrite_active_call_state() -> None:
    """Late idempotent result append preserves a terminal Run projection."""
    manager = _SessionManager()
    runs = _RunRepository(
        manager,
        _RunState(
            status=AgentRunStatus.COMPLETED,
            active_tool_calls=[],
        ),
    )
    repository = EngineToolResultOperationRepository(
        session_manager=manager,
        run_repository=runs,
        transcript_repository=_TranscriptRepository(manager),
    )

    await repository.finalize(
        run_id="run-1",
        session_id="session-1",
        call=_Call("call-1", "tool-call-1", "json_function"),
        result=ClientToolResultPayload(
            call_id="call-1",
            name="tool-call-1",
            wire_dialect="json_function",
            status="completed",
            output=[],
        ),
    )

    assert runs.updates == []


async def test_identity_mismatch_aborts_completed_operation() -> None:
    """Mismatched result identity commits no transaction."""
    manager = _SessionManager()
    repository = EngineToolResultOperationRepository(
        session_manager=manager,
        run_repository=_RunRepository(
            manager,
            _RunState(status=AgentRunStatus.RUNNING, active_tool_calls=[]),
        ),
        transcript_repository=_TranscriptRepository(manager),
    )

    with pytest.raises(ValueError, match="call ID"):
        await repository.finalize(
            run_id="run-1",
            session_id="session-1",
            call=_Call("call-1", "tool-call-1", "json_function"),
            result=ClientToolResultPayload(
                call_id="call-2",
                name="tool-call-1",
                wire_dialect="json_function",
                status="completed",
                output=[],
            ),
        )

    assert manager.sessions[0].commit_count == 0
