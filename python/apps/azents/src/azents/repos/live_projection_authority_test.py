"""PostgreSQL authority and detached completion checks for live projection."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRunStatus,
    AgentSessionProductMode,
    AgentSessionRunState,
)
from azents.engine.events.types import AgentRunState
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_execution.data import AgentRunCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession, AgentSessionCreate
from azents.repos.agent_session.repository_test import _create_agent, _create_workspace
from azents.repos.live_projection_authority import LiveProjectionAuthorityRepository


async def _create_session(manager: SessionManager[AsyncSession], *, handle: str) -> str:
    async with manager() as session:
        workspace_id = await _create_workspace(session, handle)
        agent_id = await _create_agent(session, workspace_id, handle)
        created = await AgentSessionRepository().create(
            session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                agent_id=agent_id,
                title=None,
            ),
        )
    return created.id


async def test_missing_projection_authority_preserves_distinct_owner_and_terminal_rules(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Missing owner suppresses writes; missing current Run permits terminal cleanup."""
    sessions: list[AsyncSession] = []
    active: list[AsyncSession] = []

    @asynccontextmanager
    async def tracked() -> AsyncIterator[AsyncSession]:
        async with rdb_session_manager() as session:
            active.append(session)
            sessions.append(session)
            try:
                yield session
            finally:
                active.remove(session)

    repository = LiveProjectionAuthorityRepository(
        session_manager=tracked,
        agent_session_repository=AgentSessionRepository(),
        agent_run_repository=AgentRunRepository(),
    )
    missing_id = "0" * 32
    assert (
        await repository.owns_generation(session_id=missing_id, owner_generation=1)
        is False
    )
    assert not active and all(not session.in_transaction() for session in sessions)
    assert (
        await repository.terminal_matches_current_run(
            session_id=missing_id, run_id="1" * 32
        )
        is True
    )
    assert not active and all(not session.in_transaction() for session in sessions)
    assert len(sessions) == 2


async def test_owner_generation_is_the_only_projection_owner_predicate(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Idle Sessions remain eligible and takeover invalidates the old scalar result."""
    session_id = await _create_session(rdb_session_manager, handle="projection-owner")
    repository = LiveProjectionAuthorityRepository(
        session_manager=rdb_session_manager,
        agent_session_repository=AgentSessionRepository(),
        agent_run_repository=AgentRunRepository(),
    )
    async with rdb_session_manager() as session:
        current = await AgentSessionRepository().get_by_id(session, session_id)
        assert current is not None
        assert current.run_state == AgentSessionRunState.IDLE
        generation = current.owner_generation
    original = await repository.owns_generation(
        session_id=session_id, owner_generation=generation
    )
    assert type(original) is bool and original is True
    async with rdb_session_manager() as session:
        await session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == session_id)
            .values(owner_generation=generation + 1)
        )
    assert original is True
    assert (
        await repository.owns_generation(
            session_id=session_id, owner_generation=generation
        )
        is False
    )
    assert (
        await repository.owns_generation(
            session_id=session_id, owner_generation=generation + 1
        )
        is True
    )


async def test_terminal_read_uses_only_running_run_from_the_requested_session(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Pending/foreign/terminal rows do not add eligibility restrictions."""
    current_id = await _create_session(rdb_session_manager, handle="projection-current")
    foreign_id = await _create_session(rdb_session_manager, handle="projection-foreign")
    runs = AgentRunRepository()
    async with rdb_session_manager() as session:
        foreign = await runs.create(
            session,
            AgentRunCreate(
                session_id=foreign_id,
                scheduled_task_cycle_id=None,
                parent_agent_run_id=None,
            ),
        )
        pending = await runs.create(
            session,
            AgentRunCreate(
                session_id=current_id,
                status=AgentRunStatus.PENDING,
                scheduled_task_cycle_id=None,
                parent_agent_run_id=None,
            ),
        )
    repository = LiveProjectionAuthorityRepository(
        session_manager=rdb_session_manager,
        agent_session_repository=AgentSessionRepository(),
        agent_run_repository=runs,
    )
    assert (
        await repository.terminal_matches_current_run(
            session_id=current_id, run_id=foreign.id
        )
        is True
    )
    assert (
        await repository.terminal_matches_current_run(
            session_id=current_id, run_id=pending.id
        )
        is True
    )
    assert (
        await repository.terminal_matches_current_run(
            session_id=foreign_id, run_id=pending.id
        )
        is False
    )
    async with rdb_session_manager() as session:
        await session.execute(
            sa.update(RDBAgentRun)
            .where(RDBAgentRun.id == pending.id)
            .values(status=AgentRunStatus.RUNNING)
        )
    matched = await repository.terminal_matches_current_run(
        session_id=current_id, run_id=pending.id
    )
    assert type(matched) is bool and matched is True
    assert (
        await repository.terminal_matches_current_run(
            session_id=current_id, run_id=foreign.id
        )
        is False
    )
    async with rdb_session_manager() as session:
        await session.execute(
            sa.update(RDBAgentRun)
            .where(RDBAgentRun.id == pending.id)
            .values(status=AgentRunStatus.STOPPED)
        )
    assert matched is True
    assert (
        await repository.terminal_matches_current_run(
            session_id=current_id, run_id=foreign.id
        )
        is True
    )


async def test_each_projection_read_completes_one_same_session_query(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Each operation closes its own query context and returns a detached scalar."""
    session_id = await _create_session(
        rdb_session_manager, handle="projection-detached"
    )
    queried: list[AsyncSession] = []
    opened: list[AsyncSession] = []

    class TrackedSessions(AgentSessionRepository):
        async def get_by_id(
            self, session: AsyncSession, agent_session_id: str
        ) -> AgentSession | None:
            queried.append(session)
            assert session is opened[-1]
            return await super().get_by_id(session, agent_session_id)

    class TrackedRuns(AgentRunRepository):
        async def get_running_by_session_id(
            self, session: AsyncSession, *, session_id: str
        ) -> AgentRunState | None:
            queried.append(session)
            assert session is opened[-1]
            return await super().get_running_by_session_id(
                session, session_id=session_id
            )

    @asynccontextmanager
    async def tracked_manager() -> AsyncIterator[AsyncSession]:
        async with rdb_session_manager() as session:
            opened.append(session)
            yield session

    repository = LiveProjectionAuthorityRepository(
        session_manager=tracked_manager,
        agent_session_repository=TrackedSessions(),
        agent_run_repository=TrackedRuns(),
    )
    owner = await repository.owns_generation(session_id=session_id, owner_generation=0)
    terminal = await repository.terminal_matches_current_run(
        session_id=session_id, run_id="1" * 32
    )
    assert type(owner) is bool
    assert type(terminal) is bool
    assert len(opened) == len(queried) == 2
    assert all(not session.in_transaction() for session in opened)
    assert queried == opened
