"""Real database checks for execution-bound Toolkit state."""

from azents.core.agent_session_data import AgentSessionCreate
from azents.core.engine_tool_state import TodoItem, TodoState
from azents.core.enums import AgentSessionProductMode
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.repository_test import _create_agent, _create_workspace
from azents.repos.toolkit_state.engine import TodoStateStore


async def test_private_todo_state_does_not_inherit_execution_owner_fence(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Todo metadata remains independent of foreground ownership handover."""
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

    store = TodoStateStore(session_manager=rdb_session_manager)
    await store.replace(
        agent_id,
        created.id,
        TodoState(items=[TodoItem(content="current", status="in_progress")]),
    )

    async with rdb_session_manager() as session:
        next_generation = await sessions.claim_owner_generation(session, created.id)
    assert next_generation == generation + 1

    await store.replace(
        agent_id,
        created.id,
        TodoState(items=[TodoItem(content="updated", status="completed")]),
    )

    current = await TodoStateStore(session_manager=rdb_session_manager).load(
        agent_id,
        created.id,
    )
    assert [item.content for item in current.items] == ["updated"]
