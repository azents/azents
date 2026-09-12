"""Real database checks for Session-owner-bound execution transactions."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
import sqlalchemy as sa
from psycopg.errors import LockNotAvailable
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.enums import AgentSessionProductMode
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.session_agent import RDBSessionAgent
from azents.rdb.session import SessionManager
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSessionCreate
from azents.repos.agent_session.repository_test import _create_agent, _create_workspace
from azents.repos.session_execution import (
    CanonicalExecutionOwnerGenerationStaleError,
)
from azents.repos.session_execution.ownership import OwnerBoundSessionManager


async def test_owner_bound_transaction_rejects_superseded_generation(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A new durable claim revokes both old writes and external admission checks."""
    sessions = AgentSessionRepository()
    async with rdb_session_manager() as session:
        workspace_id = await _create_workspace(session, "owner-bound-db")
        agent_id = await _create_agent(session, workspace_id, "owner-bound-db")
        created = await sessions.create(
            session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                agent_id=agent_id,
                title=None,
            ),
        )
        generation = await sessions.claim_owner_generation(session, created.id)
    old_owner = OwnerBoundSessionManager(
        session_manager=rdb_session_manager,
        session_id=created.id,
        owner_generation=generation,
    )
    await old_owner.assert_current()

    async with rdb_session_manager() as session:
        next_generation = await sessions.claim_owner_generation(session, created.id)
    assert next_generation == generation + 1

    entered = False
    with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
        async with old_owner():
            entered = True
    assert not entered
    with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
        await old_owner.assert_current()

    new_owner = OwnerBoundSessionManager(
        session_manager=rdb_session_manager,
        session_id=created.id,
        owner_generation=next_generation,
    )
    await new_owner.assert_current()


async def test_owner_bound_transaction_rejects_missing_session(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Missing durable authority must never become an unfenced execution scope."""
    owner = OwnerBoundSessionManager(
        session_manager=rdb_session_manager,
        session_id="0" * 32,
        owner_generation=1,
    )
    with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
        await owner.assert_current()


@pytest.mark.parametrize("contended_row", ["agent", "session", "parent_session"])
async def test_execution_lock_contention_releases_tree_gate_before_retry(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    contended_row: str,
) -> None:
    """Concurrent FK or Session writers never trap the root gate in a cycle."""
    del latest_db_schema

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as session:
            yield session
            await session.commit()

    suffix = uuid4().hex[:8]
    sessions = AgentSessionRepository()
    async with session_manager() as session:
        workspace_id = await _create_workspace(
            session, f"owner-lock-contention-{contended_row}-{suffix}"
        )
        agent_id = await _create_agent(
            session, workspace_id, f"owner-lock-contention-{contended_row}-{suffix}"
        )
        created = await sessions.create(
            session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                agent_id=agent_id,
                title=None,
            ),
        )
        root = await sessions.get_session_agent_by_session_id(session, created.id)
        assert root is not None
        child = await sessions.create_child_session_agent(
            session,
            parent_session_agent_id=root.id,
            name="execution-child",
            agent_type="default",
            title=None,
            last_task_message=None,
        )
        generation = await sessions.claim_owner_generation(
            session, child.agent_session_id
        )

    async with session_manager() as holder:
        if contended_row == "agent":
            await holder.scalar(
                sa.select(RDBAgent.id).where(RDBAgent.id == agent_id).with_for_update()
            )
        else:
            await holder.scalar(
                sa.select(RDBAgentSession.id)
                .where(
                    RDBAgentSession.id
                    == (
                        created.id
                        if contended_row == "parent_session"
                        else child.agent_session_id
                    )
                )
                .with_for_update()
            )
        async with session_manager() as contender:
            with pytest.raises(OperationalError) as error:
                await sessions.lock_execution_by_id(contender, child.agent_session_id)
            assert isinstance(error.value.orig, LockNotAvailable)
            # The competing writer can enter the tree lifecycle immediately:
            # the failed execution attempt retained neither gate nor Session.
            assert (
                await holder.scalar(
                    sa.select(RDBSessionAgent.id)
                    .where(RDBSessionAgent.id == root.id)
                    .with_for_update(nowait=True)
                )
                == root.id
            )
            assert (
                await holder.scalar(
                    sa.select(RDBAgentSession.id)
                    .where(RDBAgentSession.id == child.agent_session_id)
                    .with_for_update(nowait=True)
                )
                == child.agent_session_id
            )
        await holder.commit()

    await OwnerBoundSessionManager(
        session_manager=session_manager,
        session_id=child.agent_session_id,
        owner_generation=generation,
    ).assert_current()
