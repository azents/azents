"""Exact Goal identity survives edits and fences replacement mutations."""

import datetime

import pytest

from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.goal.store import GoalNotActiveError, GoalStateStore
from azents.services.mailbox_test import _create_fixture


async def test_goal_identity_survives_control_and_rejects_replaced_goal(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    session_id, _ = await _create_fixture(rdb_session_manager, "goal-exact-identity")
    async with rdb_session_manager() as session:
        canonical = await session.read_session.get(RDBAgentSession, session_id)
        assert canonical is not None
        agent_id = canonical.agent_id
    store = GoalStateStore(session_manager=rdb_session_manager, owner=None)
    now = datetime.datetime.now(datetime.UTC).isoformat()
    original = await store.create(
        agent_id=agent_id,
        session_id=session_id,
        objective="Verify the complete objective",
        updated_at=now,
    )
    assert original.goal_id is not None
    assert len(original.goal_id) == 32
    edited = await store.update_objective(
        agent_id=agent_id,
        session_id=session_id,
        objective="Verify the refined complete objective",
        updated_at=now,
    )
    assert edited.updated.goal_id == original.goal_id
    paused = await store.set_control_status(
        agent_id=agent_id,
        session_id=session_id,
        status="paused",
        updated_at=now,
    )
    assert paused.updated.goal_id == original.goal_id
    resumed = await store.set_control_status(
        agent_id=agent_id,
        session_id=session_id,
        status="active",
        updated_at=now,
    )
    assert resumed.updated.goal_id == original.goal_id
    await store.set_status(
        agent_id=agent_id,
        session_id=session_id,
        goal_id=original.goal_id,
        status="complete",
        updated_at=now,
    )
    replacement = await store.create(
        agent_id=agent_id,
        session_id=session_id,
        objective=original.objective or "Verify the complete objective",
        updated_at=now,
    )
    assert replacement.goal_id is not None
    assert replacement.goal_id != original.goal_id
    with pytest.raises(GoalNotActiveError, match="selected Goal"):
        await store.set_status(
            agent_id=agent_id,
            session_id=session_id,
            goal_id=original.goal_id,
            status="complete",
            updated_at=now,
        )
    assert await store.load(agent_id, session_id) == replacement
    completed = await store.set_status(
        agent_id=agent_id,
        session_id=session_id,
        goal_id=replacement.goal_id,
        status="complete",
        updated_at=now,
    )
    assert completed.updated.goal_id == replacement.goal_id
    assert completed.updated.status == "complete"
