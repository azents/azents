"""Completed, read-only Session Context snapshot operation tests."""

import asyncio
import dataclasses
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from azcommon.result import Failure, Success
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.agent_session_data import AgentSessionCreate
from azents.core.chat_data import NotWorkspaceMember, SessionNotFound
from azents.core.enums import (
    AgentRuntimeCapability,
    AgentSessionKind,
    AgentSessionStatus,
    EventKind,
    WorkspaceUserRole,
)
from azents.engine.events.types import (
    SystemPromptAnalysisPayload,
    SystemPromptFragmentPayload,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.conversation import RDBConversation
from azents.rdb.models.event import RDBEvent
from azents.rdb.models.user import RDBUser
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session_capabilities import (
    ReadSession,
    create_read_only_session_manager,
    create_read_write_session_manager,
)
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session_system_prompt_snapshot import (
    AgentSessionSystemPromptSnapshotRepository,
)
from azents.repos.chat_context_snapshot import SessionContextSnapshotRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.services.chat.context import SessionContextService
from azents.testing.model_selection import (
    make_test_model_selection_dict,
    make_test_selectable_model_option_dicts,
)


@dataclasses.dataclass(frozen=True)
class _ContextRows:
    workspace_id: str
    agent_id: str
    session_id: str
    empty_session_id: str
    user_id: str
    event_ids: tuple[str, ...]


def _prompt(content: str) -> SystemPromptAnalysisPayload:
    """Build actual prompt content independently of the transcript window."""
    return SystemPromptAnalysisPayload(
        final_prompt=SystemPromptFragmentPayload(
            id="final",
            source="final",
            label="Final prompt",
            content=content,
            preview=content,
            length=len(content),
            metadata={"fixture": "detached"},
        )
    )


@pytest_asyncio.fixture
async def context_rows(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> AsyncIterator[_ContextRows]:
    """Commit isolated evidence so production read-only scopes can observe it."""
    writes = create_read_write_session_manager(rdb_engine)
    async with writes() as session:
        workspace = RDBWorkspace(name="Context snapshot test", handle=uuid4().hex)
        session.write_session.add(workspace)
        await session.write_session.flush()
        user = await UserRepository().create(
            session, UserCreate(email=f"{uuid4().hex}@example.com")
        )
        session.write_session.add(
            RDBWorkspaceUser(
                workspace_id=workspace.id,
                user_id=user.id,
                name="Context reader",
                role=WorkspaceUserRole.MEMBER,
            )
        )
        selection = make_test_model_selection_dict()
        agent = RDBAgent(
            workspace_id=workspace.id,
            name="Context snapshot test",
            runtime_capability=AgentRuntimeCapability.NONE,
            model_selection=selection,
            lightweight_model_selection=selection,
            selectable_model_options=make_test_selectable_model_option_dicts(
                model_selection=selection, lightweight_model_selection=selection
            ),
            main_model_label="main",
            lightweight_model_label="lightweight",
        )
        session.write_session.add(agent)
        await session.write_session.flush()
        sessions = [
            await AgentSessionRepository().create(
                session,
                AgentSessionCreate(
                    workspace_id=workspace.id,
                    agent_id=agent.id,
                    session_kind=AgentSessionKind.SUBAGENT,
                    product_mode=None,
                    associated_user_id=None,
                    title=None,
                ),
            )
            for _ in range(2)
        ]
        events = [
            RDBEvent(
                session_id=sessions[0].id,
                kind=EventKind.USER_MESSAGE,
                payload={"sender_user_id": user.id, "content": f"message-{index}"},
            )
            for index in range(502)
        ]
        session.write_session.add_all(list(reversed(events)))
        session.write_session.add(
            RDBEvent(
                session_id=sessions[0].id,
                kind=EventKind.USER_MESSAGE,
                payload={"sender_user_id": user.id, "content": "reverted"},
                reverted=True,
            )
        )
        await AgentSessionSystemPromptSnapshotRepository().replace(
            session,
            session_id=sessions[0].id,
            system_prompt=_prompt("saved system prompt"),
        )
        rows = _ContextRows(
            workspace_id=workspace.id,
            agent_id=agent.id,
            session_id=sessions[0].id,
            empty_session_id=sessions[1].id,
            user_id=user.id,
            event_ids=tuple(sorted(event.id for event in events)),
        )
    try:
        yield rows
    finally:
        async with writes() as session:
            await session.write_session.execute(
                sa.delete(RDBAgentSession).where(
                    RDBAgentSession.agent_id == rows.agent_id
                )
            )
            await session.write_session.execute(
                sa.delete(RDBAgent).where(RDBAgent.id == rows.agent_id)
            )
            await session.write_session.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id == rows.workspace_id)
            )
            await session.write_session.execute(
                sa.delete(RDBUser).where(RDBUser.id == rows.user_id)
            )


def _repository(
    engine: AsyncEngine, opened: list[AsyncSession]
) -> SessionContextSnapshotRepository:
    """Observe production read scopes without replacing their lifecycle."""
    reads = create_read_only_session_manager(engine)

    @asynccontextmanager
    async def manager() -> AsyncIterator[ReadSession]:
        async with reads() as session:
            opened.append(session.read_session)
            assert (
                await session.read_session.scalar(sa.text("SHOW transaction_read_only"))
                == "on"
            )
            yield session

    return SessionContextSnapshotRepository(
        session_manager=manager,
        agent_session_repository=AgentSessionRepository(),
        workspace_user_repository=WorkspaceUserRepository(),
        transcript_repository=EventTranscriptRepository(),
        system_prompt_snapshot_repository=AgentSessionSystemPromptSnapshotRepository(),
    )


@pytest.mark.parametrize(("limit", "expected"), [(0, 1), (2, 2), (999, 500)])
async def test_ordered_bounded_detached_snapshot(
    rdb_engine: AsyncEngine, context_rows: _ContextRows, limit: int, expected: int
) -> None:
    """The most recent bounded Events retain ascending ID order after closure."""
    opened: list[AsyncSession] = []
    repository = _repository(rdb_engine, opened)
    result = await repository.read(
        agent_id=context_rows.agent_id,
        session_id=context_rows.session_id,
        user_id=context_rows.user_id,
        limit=limit,
    )
    assert isinstance(result, Success)
    assert (
        tuple(event.id for event in result.value.events)
        == (context_rows.event_ids[-expected:])
    )
    assert result.value.system_prompt == _prompt("saved system prompt")
    assert result.value.session.id == context_rows.session_id
    assert len(opened) == 1 and not opened[0].in_transaction()
    assert all(event.model_dump() for event in result.value.events)


@pytest.mark.parametrize("denial", ["missing", "wrong-agent", "archived", "membership"])
async def test_authority_checks(
    rdb_engine: AsyncEngine, context_rows: _ContextRows, denial: str
) -> None:
    """Preserve the exact Session/Agent/ACTIVE predicate and membership denial."""
    if denial == "archived":
        writes = create_read_write_session_manager(rdb_engine)
        async with writes() as session:
            await session.write_session.execute(
                sa.update(RDBAgentSession)
                .where(RDBAgentSession.id == context_rows.session_id)
                .values(status=AgentSessionStatus.ARCHIVED)
            )
    opened: list[AsyncSession] = []
    result = await _repository(rdb_engine, opened).read(
        agent_id=uuid4().hex if denial == "wrong-agent" else context_rows.agent_id,
        session_id=uuid4().hex if denial == "missing" else context_rows.session_id,
        user_id=uuid4().hex if denial == "membership" else context_rows.user_id,
        limit=2,
    )
    assert isinstance(result, Failure)
    if denial == "membership":
        assert isinstance(result.error, NotWorkspaceMember)
    else:
        assert isinstance(result.error, SessionNotFound)
    assert len(opened) == 1 and not opened[0].in_transaction()


async def test_empty_context_is_built_after_read_scope_closes(
    rdb_engine: AsyncEngine, context_rows: _ContextRows
) -> None:
    """No transcript or prompt remains a successful detached presentation."""
    opened: list[AsyncSession] = []
    service = SessionContextService(snapshot_repository=_repository(rdb_engine, opened))
    result = await service.get_session_context(
        agent_id=context_rows.agent_id,
        session_id=context_rows.empty_session_id,
        user_id=context_rows.user_id,
        limit=2,
    )
    assert isinstance(result, Success)
    assert result.value.stats.total_events == 0
    assert result.value.raw_events == []
    assert result.value.system_prompt is None
    assert len(opened) == 1 and not opened[0].in_transaction()


async def test_snapshot_finishes_while_writer_holds_authority_and_prompt(
    rdb_engine: AsyncEngine, context_rows: _ContextRows
) -> None:
    """Inspection reads committed data without waiting for descriptive row locks."""
    writes = create_read_write_session_manager(rdb_engine)
    opened: list[AsyncSession] = []
    repository = _repository(rdb_engine, opened)
    locked = asyncio.Event()
    release = asyncio.Event()

    async def holder() -> None:
        async with writes() as session:
            await session.write_session.execute(
                sa.update(RDBConversation)
                .where(RDBConversation.session_id == context_rows.session_id)
                .values(title="uncommitted title")
            )
            await session.write_session.execute(
                sa.update(RDBWorkspaceUser)
                .where(
                    RDBWorkspaceUser.workspace_id == context_rows.workspace_id,
                    RDBWorkspaceUser.user_id == context_rows.user_id,
                )
                .values(role=WorkspaceUserRole.MANAGER)
            )
            await AgentSessionSystemPromptSnapshotRepository().replace(
                session,
                session_id=context_rows.session_id,
                system_prompt=_prompt("uncommitted system prompt"),
            )
            await session.write_session.execute(
                sa.select(RDBEvent.id)
                .where(RDBEvent.session_id == context_rows.session_id)
                .with_for_update()
            )
            locked.set()
            await release.wait()
            await session.write_session.rollback()

    task = asyncio.create_task(holder())
    try:
        await asyncio.wait_for(locked.wait(), timeout=5)
        result = await asyncio.wait_for(
            repository.read(
                agent_id=context_rows.agent_id,
                session_id=context_rows.session_id,
                user_id=context_rows.user_id,
                limit=2,
            ),
            timeout=5,
        )
        assert isinstance(result, Success)
        assert result.value.session.title is None
        assert result.value.system_prompt == _prompt("saved system prompt")
        assert (
            tuple(event.id for event in result.value.events)
            == (context_rows.event_ids[-2:])
        )
        assert not release.is_set()
        assert len(opened) == 1 and not opened[0].in_transaction()
    finally:
        release.set()
        await task


@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_exception_and_cancellation_roll_back_read_scope(
    rdb_engine: AsyncEngine, latest_db_schema: None, error_type: type[BaseException]
) -> None:
    """Both failures propagate and roll back the exact owned transaction."""
    opened: list[AsyncSession] = []
    repository = _repository(rdb_engine, opened)
    rollback_connections: list[sa.Connection] = []

    class FailingSessions(AgentSessionRepository):
        async def get_by_id(self, session: ReadSession, agent_session_id: str) -> None:
            raise error_type("snapshot interrupted")

    repository.agent_session_repository = FailingSessions()

    def record_rollback(connection: sa.Connection) -> None:
        rollback_connections.append(connection)

    sqlalchemy_event.listen(rdb_engine.sync_engine, "rollback", record_rollback)
    try:
        with pytest.raises(error_type, match="snapshot interrupted"):
            await repository.read(
                agent_id="agent", session_id="session", user_id="user", limit=1
            )
        assert len(rollback_connections) == 1
        assert len(opened) == 1 and not opened[0].in_transaction()
    finally:
        sqlalchemy_event.remove(rdb_engine.sync_engine, "rollback", record_rollback)
