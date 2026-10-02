"""Session-bound Memory context snapshot service tests."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentSessionProductMode, EventKind
from azents.core.historical_memory_snapshot import (
    HistoricalMemorySnapshotCandidate,
    MemoryContextSnapshotState,
    MemorySnapshotConsumer,
    SavedMemorySnapshotEntry,
)
from azents.engine.events.types import CompactionSummaryPayload, Event
from azents.rdb.session import SessionManager
from azents.repos.historical_memory import HistoricalMemoryRepository
from azents.repos.memory import MemoryRepository
from azents.repos.memory.data import Memory, MemoryScope
from azents.repos.message import MessageRepository
from azents.repos.toolkit_state import ToolkitStateRepository
from azents.repos.toolkit_state.data import ToolkitStateRecord
from azents.services.historical_memory.context_snapshot import (
    MemoryContextSnapshotService,
)

_NOW = datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC)


def _consumer(*, head: str | None = None) -> MemorySnapshotConsumer:
    return MemorySnapshotConsumer(
        session_id="s" * 32,
        agent_id="a" * 32,
        workspace_id="w" * 32,
        product_mode=AgentSessionProductMode.TEAM,
        associated_user_id=None,
        model_input_head_event_id=head,
    )


def _memory() -> Memory:
    return Memory(
        id="m" * 32,
        agent_id="a" * 32,
        user_id=None,
        scope=MemoryScope.AGENT,
        type="project",
        name="project-state",
        description="Current project state",
        content="Full content",
        created_at=_NOW,
        updated_at=_NOW,
    )


def _historical() -> HistoricalMemorySnapshotCandidate:
    return HistoricalMemorySnapshotCandidate(
        source_session_id="h" * 32,
        source_scope="team",
        source_title="Prior work",
        source_activity_through=_NOW - datetime.timedelta(hours=8),
        prepared_at=_NOW - datetime.timedelta(hours=1),
        summary="The user approved the boundary snapshot design.",
    )


def _record(snapshot: MemoryContextSnapshotState) -> ToolkitStateRecord:
    return ToolkitStateRecord(
        id="t" * 32,
        agent_id="a" * 32,
        session_id="s" * 32,
        toolkit_namespace="memory",
        state_name="context_snapshot",
        state_json=snapshot.model_dump(mode="json"),
        schema_version=1,
        version=1,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _service(
    *,
    session: AsyncSession,
    historical: AsyncMock,
    memory: AsyncMock,
    message: AsyncMock,
    toolkit_state: AsyncMock,
) -> tuple[MemoryContextSnapshotService, SessionManager[AsyncSession]]:
    @asynccontextmanager
    async def session_manager() -> AsyncIterator[AsyncSession]:
        yield session

    return (
        MemoryContextSnapshotService(
            historical_repository=historical,
            memory_repository=memory,
            message_repository=message,
            toolkit_state_repository=toolkit_state,
        ),
        session_manager,
    )


async def test_initial_boundary_selects_persists_and_renders_snapshot() -> None:
    """The first model boundary persists even when selection is small."""
    session = AsyncMock(spec=AsyncSession)
    historical = AsyncMock(spec=HistoricalMemoryRepository)
    historical.get_snapshot_consumer_in_session.return_value = _consumer()
    historical.list_available_snapshot_candidates_in_session.side_effect = [
        [_historical()],
        [_historical()],
    ]
    memory = AsyncMock(spec=MemoryRepository)
    memory.list.return_value = [_memory()]
    memory.list_by_ids.return_value = [_memory()]
    message = AsyncMock(spec=MessageRepository)
    message.has_non_reverted_kind.return_value = False
    toolkit_state = AsyncMock(spec=ToolkitStateRepository)
    toolkit_state.get.return_value = None
    toolkit_state.save.return_value = AsyncMock()
    service, session_manager = _service(
        session=session,
        historical=historical,
        memory=memory,
        message=message,
        toolkit_state=toolkit_state,
    )

    prompt = await service.prompt_for_turn(
        session_id="s" * 32,
        session_manager=session_manager,
    )

    assert "project-state" in prompt
    assert "boundary snapshot design" in prompt
    assert f"azents://memory/saved/agent/{'m' * 32}.md" in prompt
    assert f"azents://memory/historical/team/{'h' * 32}/summary.md" in prompt
    assert f"azents://memory/sources/team/{'h' * 32}/session.md" in prompt
    toolkit_state.save.assert_awaited_once()
    session.commit.assert_not_awaited()


async def test_ordinary_turn_filters_stored_entries_without_reselection() -> None:
    """A matching boundary loads frozen text and removes unavailable IDs only."""
    snapshot = MemoryContextSnapshotState(
        boundary_head_event_id=None,
        created_at=_NOW,
        saved_entries=[
            SavedMemorySnapshotEntry(
                memory_id="m" * 32,
                scope="agent",
                name="frozen-name",
                type="project",
                description_snapshot="Frozen description",
                updated_at_snapshot=_NOW,
                vfs_path=f"azents://memory/saved/agent/{'m' * 32}.md",
            )
        ],
        historical_entries=[],
    )
    session = AsyncMock(spec=AsyncSession)
    historical = AsyncMock(spec=HistoricalMemoryRepository)
    historical.get_snapshot_consumer_in_session.return_value = _consumer()
    historical.list_available_snapshot_candidates_in_session.return_value = []
    memory = AsyncMock(spec=MemoryRepository)
    memory.list_by_ids.return_value = [_memory()]
    message = AsyncMock(spec=MessageRepository)
    message.has_non_reverted_kind.return_value = True
    toolkit_state = AsyncMock(spec=ToolkitStateRepository)
    toolkit_state.get.return_value = _record(snapshot)
    service, session_manager = _service(
        session=session,
        historical=historical,
        memory=memory,
        message=message,
        toolkit_state=toolkit_state,
    )

    prompt = await service.prompt_for_turn(
        session_id="s" * 32,
        session_manager=session_manager,
    )

    assert "frozen-name" in prompt
    assert "Frozen description" in prompt
    memory.list.assert_not_awaited()
    toolkit_state.save.assert_not_awaited()


async def test_missing_snapshot_outside_explicit_boundary_contributes_no_memory() -> (
    None
):
    """Ordinary turns do not reconstruct a missing boundary snapshot."""
    session = AsyncMock(spec=AsyncSession)
    historical = AsyncMock(spec=HistoricalMemoryRepository)
    historical.get_snapshot_consumer_in_session.return_value = _consumer()
    memory = AsyncMock(spec=MemoryRepository)
    message = AsyncMock(spec=MessageRepository)
    message.has_non_reverted_kind.return_value = True
    toolkit_state = AsyncMock(spec=ToolkitStateRepository)
    toolkit_state.get.return_value = None
    service, session_manager = _service(
        session=session,
        historical=historical,
        memory=memory,
        message=message,
        toolkit_state=toolkit_state,
    )

    assert (
        await service.prompt_for_turn(
            session_id="s" * 32,
            session_manager=session_manager,
        )
        == ""
    )
    memory.list.assert_not_awaited()
    toolkit_state.save.assert_not_awaited()


async def test_committed_compaction_head_reselects_once_then_keeps_snapshot() -> None:
    """Only a new committed summary head selects the next frozen snapshot."""
    head = "c" * 32
    previous = MemoryContextSnapshotState(
        boundary_head_event_id=None,
        created_at=_NOW,
        saved_entries=[],
        historical_entries=[],
    )
    session = AsyncMock(spec=AsyncSession)
    historical = AsyncMock(spec=HistoricalMemoryRepository)
    historical.get_snapshot_consumer_in_session.return_value = _consumer(head=head)
    historical.list_available_snapshot_candidates_in_session.return_value = [
        _historical()
    ]
    memory = AsyncMock(spec=MemoryRepository)
    memory.list.return_value = [_memory()]
    memory.list_by_ids.return_value = [_memory()]
    message = AsyncMock(spec=MessageRepository)
    message.get_event_by_id.return_value = Event(
        id=head,
        session_id="s" * 32,
        kind=EventKind.COMPACTION_SUMMARY,
        payload=CompactionSummaryPayload(
            compaction_id="compaction-1",
            content="Continue the approved boundary snapshot design.",
        ),
        created_at=_NOW,
    )
    toolkit_state = AsyncMock(spec=ToolkitStateRepository)
    toolkit_state.get.return_value = _record(previous)
    service, session_manager = _service(
        session=session,
        historical=historical,
        memory=memory,
        message=message,
        toolkit_state=toolkit_state,
    )

    prompt = await service.prompt_for_turn(
        session_id="s" * 32,
        session_manager=session_manager,
    )

    assert "boundary snapshot design" in prompt
    toolkit_state.save.assert_awaited_once()
    upsert = toolkit_state.save.await_args.args[1]
    selected = MemoryContextSnapshotState.model_validate(upsert.state_json)
    assert selected.boundary_head_event_id == head
    assert upsert.expected_version == 1
    assert selected.historical_entries[0].source_session_id == "h" * 32

    toolkit_state.get.return_value = _record(selected)
    toolkit_state.save.reset_mock()
    memory.list.reset_mock()
    historical.list_available_snapshot_candidates_in_session.reset_mock()
    again = await service.prompt_for_turn(
        session_id="s" * 32,
        session_manager=session_manager,
    )
    assert again == prompt
    toolkit_state.save.assert_not_awaited()
    memory.list.assert_not_awaited()
    query = historical.list_available_snapshot_candidates_in_session.await_args
    assert query.kwargs["source_session_ids"] == ["h" * 32]


@pytest.mark.parametrize("foreign_summary", [False, True])
async def test_uncommitted_or_foreign_head_cannot_reselect_memory(
    foreign_summary: bool,
) -> None:
    """Missing or other-Session heads are not successful compaction boundaries."""
    head = "c" * 32
    session = AsyncMock(spec=AsyncSession)
    historical = AsyncMock(spec=HistoricalMemoryRepository)
    historical.get_snapshot_consumer_in_session.return_value = _consumer(head=head)
    memory = AsyncMock(spec=MemoryRepository)
    message = AsyncMock(spec=MessageRepository)
    message.get_event_by_id.return_value = (
        Event(
            id=head,
            session_id="x" * 32,
            kind=EventKind.COMPACTION_SUMMARY,
            payload=CompactionSummaryPayload(
                compaction_id="compaction-foreign",
                content="Uncommitted or foreign summary",
            ),
            created_at=_NOW,
        )
        if foreign_summary
        else None
    )
    toolkit_state = AsyncMock(spec=ToolkitStateRepository)
    toolkit_state.get.return_value = _record(
        MemoryContextSnapshotState(
            boundary_head_event_id=None,
            created_at=_NOW,
            saved_entries=[],
            historical_entries=[],
        )
    )
    service, session_manager = _service(
        session=session,
        historical=historical,
        memory=memory,
        message=message,
        toolkit_state=toolkit_state,
    )

    assert (
        await service.prompt_for_turn(
            session_id="s" * 32,
            session_manager=session_manager,
        )
        == ""
    )
    memory.list.assert_not_awaited()
    historical.list_available_snapshot_candidates_in_session.assert_not_awaited()
    toolkit_state.save.assert_not_awaited()
