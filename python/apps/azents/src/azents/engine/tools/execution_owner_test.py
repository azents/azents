"""Real database checks for execution-bound Toolkit state."""

import pytest

from azents.core.agent_session_data import AgentSessionCreate
from azents.core.engine_tool_state import TodoItem, TodoState
from azents.core.enums import AgentSessionProductMode
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.repository_test import _create_agent, _create_workspace
from azents.repos.session_execution import (
    CanonicalExecutionOwnerGenerationStaleError,
)
from azents.repos.toolkit_state.engine import TodoStateStore


async def test_toolkit_state_store_rejects_superseded_execution_owner(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """A Toolkit state mutation cannot commit after Session takeover."""
    sessions = AgentSessionRepository()
    async with rdb_session_manager() as session:
        workspace_id = await _create_workspace(session, "toolkit-owner")
        agent_id = await _create_agent(session, workspace_id, "toolkit-owner")
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

    store = TodoStateStore(session_manager=rdb_session_manager).for_execution(
        SessionExecutionOwner(
            session_id=created.id,
            owner_generation=generation,
        )
    )
    await store.replace(
        agent_id,
        created.id,
        TodoState(items=[TodoItem(content="current", status="in_progress")]),
    )

    async with rdb_session_manager() as session:
        next_generation = await sessions.claim_owner_generation(session, created.id)
    assert next_generation == generation + 1

    with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
        await store.replace(
            agent_id,
            created.id,
            TodoState(items=[TodoItem(content="stale", status="completed")]),
        )

    current = await TodoStateStore(session_manager=rdb_session_manager).load(
        agent_id,
        created.id,
    )
    assert [item.content for item in current.items] == ["current"]
