"""Completed compaction operation tests."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import NamedTuple

import pytest
from azcommon.di import Container
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.engine_tool_state import ToolWorkingSetState
from azents.core.enums import EventKind
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.engine.events.filters import EventCompactor
from azents.engine.events.types import Event, validate_event_payload
from azents.rdb.deps import get_session_manager
from azents.rdb.session_capabilities import ReadSession, ReadWriteSession, WriteSession
from azents.repos.agent_execution.data import EventCreate
from azents.repos.compaction_operation import (
    CompactionCommitContext,
    CompactionOperationRepository,
    get_compaction_operation_repository,
)
from azents.repos.model_operation_completion import ModelOperationCompletion
from azents.repos.toolkit_state.engine import ToolWorkingSetStore


class _Session(AsyncSession):
    """Session tracking successful operation commits."""

    def __init__(self) -> None:
        super().__init__()
        self.commit_count = 0

    async def commit(self) -> None:
        """Record one successful context exit."""
        self.commit_count += 1


class _SessionManager:
    """Create isolated operation sessions and expose active scope state."""

    def __init__(self) -> None:
        self.sessions: list[_Session] = []
        self.active = False

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[WriteSession]:
        """Yield one session and commit only on successful exit."""
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


class _TranscriptRepository:
    """Append deterministic in-memory Events."""

    def __init__(self, manager: _SessionManager) -> None:
        self.manager = manager
        self.events: list[Event] = []

    async def append(self, session: ReadSession, create: EventCreate) -> Event:
        """Append while the operation transaction is active."""
        assert self.manager.active
        assert session.read_session is self.manager.sessions[-1]
        event = Event(
            id=f"{len(self.events) + 1:032d}",
            session_id=create.session_id,
            kind=create.kind,
            payload=validate_event_payload(create.kind, create.payload),
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.events.append(event)
        return event


class _AgentSessionRepository:
    """Provide plan state and record final head movement."""

    def __init__(self, manager: _SessionManager, *, current: bool = True) -> None:
        self.manager = manager
        self.current = current
        self.model_input_head_event_id: str | None = None
        self.moved_head_event_id: str | None = None

    async def get_by_id(
        self,
        session: ReadSession,
        agent_session_id: str,
    ) -> "_AgentSessionRepository":
        """Return the detached planning state."""
        del agent_session_id
        assert self.manager.active
        assert session.read_session is self.manager.sessions[-1]
        return self

    async def lock_compaction_plan_if_current(
        self,
        session: ReadSession,
        *,
        session_id: str,
        expected_head_event_id: str | None,
        expected_tail_event_id: str,
    ) -> bool:
        """Return the configured stale-plan result."""
        del session_id, expected_tail_event_id
        assert self.manager.active
        assert session.read_session is self.manager.sessions[-1]
        assert expected_head_event_id == self.model_input_head_event_id
        return self.current

    async def move_model_input_head(
        self,
        session: ReadSession,
        session_id: str,
        event_id: str,
    ) -> object:
        """Record movement after marker and summary append."""
        del session_id
        assert self.manager.active
        assert session.read_session is self.manager.sessions[-1]
        self.moved_head_event_id = event_id
        self.model_input_head_event_id = event_id
        return object()


class _ModelOperationCompletionRepository:
    """Record operation success settlement order."""

    def __init__(
        self,
        manager: _SessionManager,
        sessions: _AgentSessionRepository,
        transcript: _TranscriptRepository,
        *,
        error: Exception | None = None,
    ) -> None:
        self.manager = manager
        self.sessions = sessions
        self.transcript = transcript
        self.error = error
        self.completions: list[ModelOperationCompletion] = []

    async def complete_success_in_session(
        self,
        session: ReadSession,
        completion: ModelOperationCompletion,
    ) -> None:
        """Settle after summary append and head movement."""
        assert self.manager.active
        assert session.read_session is self.manager.sessions[-1]
        assert [event.kind for event in self.transcript.events] == [
            EventKind.COMPACTION_MARKER,
            EventKind.COMPACTION_SUMMARY,
        ]
        assert self.sessions.moved_head_event_id == self.transcript.events[-1].id
        if self.error is not None:
            raise self.error
        self.completions.append(completion)


class _ToolWorkingSetStore(ToolWorkingSetStore):
    """Record the final Tool Search clear."""

    def __init__(
        self,
        manager: _SessionManager,
        completions: _ModelOperationCompletionRepository,
    ) -> None:
        super().__init__(session_manager=manager)
        self.manager = manager
        self.completions = completions
        self.cleared: list[tuple[str, str]] = []

    def with_session_manager(self, session_manager: object) -> "_ToolWorkingSetStore":
        """Keep the focused test store."""
        del session_manager
        return self

    async def clear_in_session(
        self,
        session: ReadSession,
        agent_id: str,
        session_id: str,
    ) -> ToolWorkingSetState:
        """Clear only after model-operation completion."""
        assert self.manager.active
        assert session.read_session is self.manager.sessions[-1]
        self.cleared.append((agent_id, session_id))
        return ToolWorkingSetState()


class _RepositoryFixture(NamedTuple):
    """Compaction repository and assertion-visible collaborators."""

    repository: CompactionOperationRepository
    manager: _SessionManager
    transcript: _TranscriptRepository
    sessions: _AgentSessionRepository
    completions: _ModelOperationCompletionRepository
    working_set: _ToolWorkingSetStore


def _repository(
    *,
    current: bool = True,
    completion_error: Exception | None = None,
) -> _RepositoryFixture:
    """Build one focused completed-operation fixture."""
    manager = _SessionManager()
    transcript = _TranscriptRepository(manager)
    sessions = _AgentSessionRepository(manager, current=current)
    completions = _ModelOperationCompletionRepository(
        manager,
        sessions,
        transcript,
        error=completion_error,
    )
    working_set = _ToolWorkingSetStore(manager, completions)
    return _RepositoryFixture(
        repository=CompactionOperationRepository(
            owner=None,
            session_manager=manager,
            transcript_repository=transcript,
            agent_session_repository=sessions,
            model_operation_completion_repository=completions,
            tool_working_set_store=working_set,
        ),
        manager=manager,
        transcript=transcript,
        sessions=sessions,
        completions=completions,
        working_set=working_set,
    )


async def test_compaction_operations_close_prepare_and_finalize_transactions() -> None:
    """Prepare and finalize return only after their transactions close."""
    repository, manager, transcript, sessions, completions, working_set = _repository()

    plan = await repository.prepare(session_id="session-1")
    assert not manager.active

    summary = await repository.finalize(
        session_id="session-1",
        plan=plan,
        expected_tail_event_id="f" * 32,
        compaction_id="compact-1",
        content="summary",
        reason="manual_command",
        commit_context=CompactionCommitContext(
            workspace_id="workspace-1",
            agent_id="agent-1",
            run_id="run-1",
            owner_generation=3,
            settle_model_operation=True,
        ),
    )

    assert summary is not None
    assert not manager.active
    assert [session.commit_count for session in manager.sessions] == [1, 1]
    assert [event.kind for event in transcript.events] == [
        EventKind.COMPACTION_MARKER,
        EventKind.COMPACTION_SUMMARY,
    ]
    assert sessions.moved_head_event_id == summary.id
    assert completions.completions[0].owner_generation == 3
    assert working_set.cleared == [("agent-1", "session-1")]


async def test_stale_compaction_plan_commits_no_mutation() -> None:
    """A stale plan returns None without append, head move, or state reset."""
    repository, manager, transcript, sessions, completions, working_set = _repository(
        current=False
    )
    plan = await repository.prepare(session_id="session-1")

    summary = await repository.finalize(
        session_id="session-1",
        plan=plan,
        expected_tail_event_id="f" * 32,
        compaction_id="compact-1",
        content="summary",
        reason=None,
        commit_context=CompactionCommitContext(
            workspace_id="workspace-1",
            agent_id="agent-1",
            run_id="run-1",
            owner_generation=1,
            settle_model_operation=True,
        ),
    )

    assert summary is None
    assert not manager.active
    assert transcript.events == []
    assert sessions.moved_head_event_id is None
    assert completions.completions == []
    assert working_set.cleared == []


async def test_compaction_clear_does_not_require_model_operation_settlement() -> None:
    """Tool Search still clears when no model-operation callback was configured."""
    repository, _, _, _, completions, working_set = _repository()
    plan = await repository.prepare(session_id="session-1")

    await repository.finalize(
        session_id="session-1",
        plan=plan,
        expected_tail_event_id="f" * 32,
        compaction_id="compact-1",
        content="summary",
        reason=None,
        commit_context=CompactionCommitContext(
            workspace_id="workspace-1",
            agent_id="agent-1",
            run_id="run-1",
            owner_generation=1,
            settle_model_operation=False,
        ),
    )

    assert completions.completions == []
    assert working_set.cleared == [("agent-1", "session-1")]


async def test_compaction_commit_state_failure_aborts_final_transaction() -> None:
    """A composed state failure prevents the final transaction commit."""
    repository, manager, _, _, _, working_set = _repository(
        completion_error=RuntimeError("settlement failed")
    )
    plan = await repository.prepare(session_id="session-1")

    with pytest.raises(RuntimeError, match="settlement failed"):
        await repository.finalize(
            session_id="session-1",
            plan=plan,
            expected_tail_event_id="f" * 32,
            compaction_id="compact-1",
            content="summary",
            reason=None,
            commit_context=CompactionCommitContext(
                workspace_id="workspace-1",
                agent_id="agent-1",
                run_id="run-1",
                owner_generation=1,
                settle_model_operation=True,
            ),
        )

    assert [session.commit_count for session in manager.sessions] == [1, 0]
    assert working_set.cleared == []


async def test_compaction_dependency_graph_binds_execution_owner_explicitly() -> None:
    """Offline production DI requires no caller-supplied owner body or query."""
    manager = _SessionManager()
    async with Container(
        dependency_overrides={get_session_manager: lambda: manager}
    ) as container:
        operation = await container.solve(get_compaction_operation_repository)
        compactor = await container.solve(EventCompactor)
        assert operation.owner is None
        assert operation.session_manager is manager
        assert compactor.operation_repository.owner is None
        owner = SessionExecutionOwner("captured-session", 7)
        bound = operation.for_execution(owner)
        assert bound.owner == owner
        assert bound.session_manager is manager
        assert operation.owner is None
