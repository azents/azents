"""Local contracts for explicit tool identities and repository-owned fencing."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.session_resource_authority import SessionExecutionOwner
from azents.repos.engine_tool_repositories import EngineMcpSnapshotFactory
from azents.repos.session_execution.ownership import OwnerBoundSessionManager


@asynccontextmanager
async def _session_manager() -> AsyncIterator[AsyncSession]:
    async with AsyncSession() as session:
        yield session


@pytest.mark.parametrize(
    ("agent_id", "session_id"),
    [(None, None), ("agent-1", None), (None, "session-1")],
)
def test_absent_snapshot_identity_is_explicit_and_does_not_open_db(
    agent_id: str | None, session_id: str | None
) -> None:
    """A missing identity has no state operation instead of an empty identifier."""
    factory = EngineMcpSnapshotFactory(session_manager=_session_manager)
    assert (
        factory.create(
            agent_id=agent_id,
            session_id=session_id,
            toolkit_namespace="mcp",
            state_name="snapshot",
        )
        is None
    )
    assert (
        factory.selected_installation(agent_id=agent_id, session_id=session_id) is None
    )


@pytest.mark.parametrize(
    ("agent_id", "session_id"), [("", "session-1"), ("agent-1", "")]
)
def test_empty_snapshot_identity_is_not_an_absence_placeholder(
    agent_id: str, session_id: str
) -> None:
    factory = EngineMcpSnapshotFactory(session_manager=_session_manager)
    with pytest.raises(ValueError, match="nonempty or absent"):
        factory.create(
            agent_id=agent_id,
            session_id=session_id,
            toolkit_namespace="mcp",
            state_name="snapshot",
        )


def test_optional_no_db_snapshot_factory_stays_unavailable() -> None:
    """No-DB provider construction retains its existing lack of persistence."""
    factory = EngineMcpSnapshotFactory(session_manager=None)
    assert (
        factory.create(
            agent_id="agent-1",
            session_id="session-1",
            toolkit_namespace="mcp",
            state_name="snapshot",
        )
        is None
    )
    assert (
        factory.selected_installation(agent_id="agent-1", session_id="session-1")
        is None
    )


def test_snapshot_owner_binding_is_immutable_and_repo_scoped() -> None:
    """Owner binding fences stores without mutating the shared factory."""
    owner = SessionExecutionOwner(session_id="session-1", owner_generation=7)
    factory = EngineMcpSnapshotFactory(session_manager=_session_manager)
    bound = factory.with_owner(owner)
    store = bound.create(
        agent_id="agent-1",
        session_id="session-1",
        toolkit_namespace="mcp",
        state_name="snapshot",
    )
    assert store is not None
    assert factory.session_manager is _session_manager
    assert isinstance(store.session_manager, OwnerBoundSessionManager)
    assert store.session_manager.session_id == "session-1"
    assert store.session_manager.owner_generation == 7
    selection = bound.selected_installation(agent_id="agent-1", session_id="session-1")
    assert selection is not None
    assert isinstance(selection.session_manager, OwnerBoundSessionManager)
    assert selection.session_manager.owner_generation == 7
