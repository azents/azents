"""Local contracts for explicit tool identities and repository-owned fencing."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.engine_tool_repositories import EngineMcpSnapshotFactory


@asynccontextmanager
async def _session_manager() -> AsyncIterator[WriteSession]:
    async with AsyncSession() as _raw_session:
        session = ReadWriteSession(_raw_session)
        yield session


@pytest.mark.parametrize(
    ("agent_id", "session_id"),
    [(None, None), ("agent-1", None), (None, "session-1")],
)
def test_absent_snapshot_identity_is_explicit_and_does_not_open_db(
    agent_id: str | None, session_id: str | None
) -> None:
    """A missing identity has no state operation instead of an empty identifier."""
    factory = EngineMcpSnapshotFactory(
        session_manager=_session_manager,
        read_session_manager=_session_manager,
    )
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
    factory = EngineMcpSnapshotFactory(
        session_manager=_session_manager,
        read_session_manager=_session_manager,
    )
    with pytest.raises(ValueError, match="nonempty or absent"):
        factory.create(
            agent_id=agent_id,
            session_id=session_id,
            toolkit_namespace="mcp",
            state_name="snapshot",
        )


def test_optional_no_db_snapshot_factory_stays_unavailable() -> None:
    """No-DB provider construction retains its existing lack of persistence."""
    factory = EngineMcpSnapshotFactory(
        session_manager=None,
        read_session_manager=None,
    )
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


def test_snapshot_factory_keeps_description_and_mutation_scopes_plain() -> None:
    """Private snapshot and selection metadata never inherit an owner gate."""
    factory = EngineMcpSnapshotFactory(
        session_manager=_session_manager,
        read_session_manager=_session_manager,
    )
    store = factory.create(
        agent_id="agent-1",
        session_id="session-1",
        toolkit_namespace="mcp",
        state_name="snapshot",
    )
    assert store is not None
    assert factory.session_manager is _session_manager
    assert store.read_session_manager is _session_manager
    assert store.session_manager is _session_manager
    selection = factory.selected_installation(
        agent_id="agent-1", session_id="session-1"
    )
    assert selection is not None
    assert selection.read_session_manager is _session_manager
    assert selection.session_manager is _session_manager
