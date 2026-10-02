"""Session-bound Memory context snapshot service tests."""

import dataclasses
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
from azents.repos.toolkit_state import (
    ToolkitStateConflictError,
    ToolkitStateRepository,
)
from azents.repos.toolkit_state.data import ToolkitStateRecord, ToolkitStateUpsert
from azents.services.historical_memory.context_snapshot import (
    MemoryContextSnapshotService,
)
from azents.services.historical_memory.snapshot import build_memory_context_snapshot

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
    """Run preparation persists Memory before the first model prompt reads it."""
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

    assert await service.refresh_snapshot(
        session_id="s" * 32,
        after_compaction=False,
        session_manager=session_manager,
    )
    selected = MemoryContextSnapshotState.model_validate(
        toolkit_state.save.await_args.args[1].state_json
    )
    toolkit_state.get.return_value = _record(selected)
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
    """Compaction refreshes the current execution without waiting for a new Run."""
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

    assert await service.refresh_snapshot(
        session_id="s" * 32,
        after_compaction=True,
        session_manager=session_manager,
    )
    toolkit_state.save.assert_awaited_once()
    upsert = toolkit_state.save.await_args.args[1]
    selected = MemoryContextSnapshotState.model_validate(upsert.state_json)
    assert selected.boundary_head_event_id == head
    assert upsert.expected_version == 1
    assert selected.historical_entries[0].source_session_id == "h" * 32

    toolkit_state.get.return_value = _record(selected)
    prompt = await service.prompt_for_turn(
        session_id="s" * 32,
        session_manager=session_manager,
    )
    assert "boundary snapshot design" in prompt
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
    assert not await service.refresh_snapshot(
        session_id="s" * 32,
        after_compaction=True,
        session_manager=session_manager,
    )
    memory.list.assert_not_awaited()
    historical.list_available_snapshot_candidates_in_session.assert_not_awaited()
    toolkit_state.save.assert_not_awaited()


@dataclasses.dataclass(frozen=True)
class _RefreshFixture:
    """Typed collaborators with deterministic in-memory snapshot persistence."""

    service: MemoryContextSnapshotService
    session_manager: SessionManager[AsyncSession]
    session: AsyncMock
    historical: AsyncMock
    memory: AsyncMock
    message: AsyncMock
    toolkit_state: AsyncMock

    async def refresh(self, *, after_compaction: bool) -> bool:
        return await self.service.refresh_snapshot(
            session_id="s" * 32,
            after_compaction=after_compaction,
            session_manager=self.session_manager,
        )

    async def prompt(self) -> str:
        return await self.service.prompt_for_turn(
            session_id="s" * 32,
            session_manager=self.session_manager,
        )


def _frozen_snapshot(*, head: str | None) -> MemoryContextSnapshotState:
    return build_memory_context_snapshot(
        boundary_head_event_id=head,
        created_at=_NOW,
        saved_memories=[_memory()],
        historical_candidates=[_historical()],
        topic=None,
    )


def _refresh_fixture(
    *,
    snapshot: MemoryContextSnapshotState | None,
    head: str | None,
) -> _RefreshFixture:
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
    toolkit_state = AsyncMock(spec=ToolkitStateRepository)
    toolkit_state.get.return_value = None if snapshot is None else _record(snapshot)

    async def save(
        db_session: AsyncSession, upsert: ToolkitStateUpsert
    ) -> ToolkitStateRecord:
        assert db_session is session
        current = toolkit_state.get.return_value
        assert current is None or isinstance(current, ToolkitStateRecord)
        assert upsert.expected_version == (None if current is None else current.version)
        selected = MemoryContextSnapshotState.model_validate(upsert.state_json)
        record = _record(selected).model_copy(
            update={"version": 1 if current is None else current.version + 1}
        )
        toolkit_state.get.return_value = record
        return record

    toolkit_state.save.side_effect = save
    service, session_manager = _service(
        session=session,
        historical=historical,
        memory=memory,
        message=message,
        toolkit_state=toolkit_state,
    )
    return _RefreshFixture(
        service=service,
        session_manager=session_manager,
        session=session,
        historical=historical,
        memory=memory,
        message=message,
        toolkit_state=toolkit_state,
    )


async def test_next_run_admits_new_summary_without_compaction() -> None:
    """Run preparation sees new prepared sources even when the head stays null."""
    fixture = _refresh_fixture(snapshot=_frozen_snapshot(head=None), head=None)
    published = _historical().model_copy(
        update={
            "source_session_id": "n" * 32,
            "summary": "New summary published after the previous Run started.",
            "prepared_at": _NOW,
        }
    )
    fixture.historical.list_available_snapshot_candidates_in_session.return_value = [
        _historical(),
        published,
    ]
    before = await fixture.prompt()
    assert "New summary published" not in before
    fixture.memory.list.assert_not_awaited()
    fixture.toolkit_state.save.assert_not_awaited()

    assert await fixture.refresh(after_compaction=False)
    after = await fixture.prompt()

    assert "New summary published" in after
    fixture.toolkit_state.save.assert_awaited_once()
    selection = (
        fixture.historical.list_available_snapshot_candidates_in_session.await_args_list
    )[1]
    assert selection.kwargs["source_session_ids"] is None
    assert selection.kwargs["limit"] == 200
    fixture.session.commit.assert_not_awaited()


async def test_next_run_refreshes_updated_summary_and_saved_index() -> None:
    """Published changes replace frozen content only at an explicit boundary."""
    fixture = _refresh_fixture(snapshot=_frozen_snapshot(head=None), head=None)
    fixture.historical.list_available_snapshot_candidates_in_session.return_value = [
        _historical().model_copy(
            update={"summary": "Updated historical result.", "prepared_at": _NOW}
        )
    ]
    updated = _memory().model_copy(
        update={
            "description": "Updated Saved index.",
            "updated_at": _NOW + datetime.timedelta(minutes=1),
        }
    )
    fixture.memory.list.return_value = [updated]
    fixture.memory.list_by_ids.return_value = [updated]

    before = await fixture.prompt()
    assert "Updated historical result" not in before
    assert "Updated Saved index" not in before
    assert await fixture.refresh(after_compaction=False)
    after = await fixture.prompt()
    assert "Updated historical result" in after
    assert "Updated Saved index" in after


async def test_unchanged_run_selection_reuses_snapshot_without_write() -> None:
    """Repeated Run preparation does not replace identical selected content."""
    frozen = _frozen_snapshot(head=None)
    fixture = _refresh_fixture(snapshot=frozen, head=None)

    assert await fixture.refresh(after_compaction=False)
    assert await fixture.refresh(after_compaction=False)

    fixture.memory.list.assert_awaited()
    assert fixture.memory.list.await_count == 2
    fixture.toolkit_state.save.assert_not_awaited()
    record = fixture.toolkit_state.get.return_value
    assert isinstance(record, ToolkitStateRecord)
    assert MemoryContextSnapshotState.model_validate(record.state_json) == frozen


@pytest.mark.parametrize("head", [None, "c" * 32])
async def test_failed_compaction_preserves_snapshot_without_reselection(
    head: str | None,
) -> None:
    """A started/cancelled compaction cannot admit new summaries with the old head."""
    fixture = _refresh_fixture(snapshot=_frozen_snapshot(head=head), head=head)
    fixture.historical.list_available_snapshot_candidates_in_session.return_value = [
        _historical().model_copy(update={"summary": "Not yet admitted."})
    ]

    assert await fixture.refresh(after_compaction=True)
    assert "Not yet admitted" not in await fixture.prompt()
    fixture.memory.list.assert_not_awaited()
    fixture.toolkit_state.save.assert_not_awaited()
    fixture.message.get_event_by_id.assert_not_awaited()


async def test_compaction_rebinds_identical_content_without_replacing_it() -> None:
    """The new committed head is persisted even when selected Memory is identical."""
    frozen = _frozen_snapshot(head=None)
    head = "c" * 32
    fixture = _refresh_fixture(snapshot=frozen, head=head)
    fixture.message.get_event_by_id.return_value = Event(
        id=head,
        session_id="s" * 32,
        kind=EventKind.COMPACTION_SUMMARY,
        payload=CompactionSummaryPayload(compaction_id="compact", content="Prior work"),
        created_at=_NOW,
    )
    assert await fixture.prompt() == ""

    assert await fixture.refresh(after_compaction=True)
    selected = MemoryContextSnapshotState.model_validate(
        fixture.toolkit_state.save.await_args.args[1].state_json
    )
    assert selected.boundary_head_event_id == head
    assert selected.created_at == frozen.created_at
    assert selected.saved_entries == frozen.saved_entries
    assert selected.historical_entries == frozen.historical_entries
    assert "boundary snapshot design" in await fixture.prompt()
    fixture.toolkit_state.save.reset_mock()
    assert await fixture.refresh(after_compaction=True)
    fixture.toolkit_state.save.assert_not_awaited()


async def test_access_loss_filters_snapshot_immediately_without_reselection() -> None:
    """Revocation remains per-input even though refresh is lifecycle-owned."""
    fixture = _refresh_fixture(snapshot=_frozen_snapshot(head=None), head=None)
    fixture.memory.list_by_ids.return_value = []
    fixture.historical.list_available_snapshot_candidates_in_session.return_value = []

    prompt = await fixture.prompt()

    assert "project-state" not in prompt
    assert "boundary snapshot design" not in prompt
    fixture.memory.list.assert_not_awaited()
    fixture.toolkit_state.save.assert_not_awaited()


async def test_disabled_or_unauthorized_consumer_cannot_refresh() -> None:
    """The refresh hook cannot bypass the same consumer authority as prompt reads."""
    fixture = _refresh_fixture(snapshot=_frozen_snapshot(head=None), head=None)
    fixture.historical.get_snapshot_consumer_in_session.return_value = None

    assert not await fixture.refresh(after_compaction=False)
    assert await fixture.prompt() == ""
    fixture.toolkit_state.get.assert_not_awaited()
    fixture.memory.list.assert_not_awaited()


async def test_refresh_cas_conflict_reports_no_prepared_snapshot() -> None:
    """Run preparation can fail closed instead of exposing the prior selection."""
    fixture = _refresh_fixture(snapshot=None, head=None)
    fixture.toolkit_state.save.side_effect = ToolkitStateConflictError("conflict")

    assert not await fixture.refresh(after_compaction=False)
    assert await fixture.prompt() == ""
    fixture.session.commit.assert_not_awaited()


@pytest.mark.parametrize("corrupt", [False, True])
async def test_explicit_run_preparation_initializes_missing_or_corrupt_state(
    corrupt: bool,
) -> None:
    """Ordinary prompt reads stay read-only; preparation owns state initialization."""
    fixture = _refresh_fixture(snapshot=None, head=None)
    if corrupt:
        record = _record(_frozen_snapshot(head=None))
        fixture.toolkit_state.get.return_value = record.model_copy(
            update={"state_json": {"schema_version": 1}}
        )
    assert await fixture.prompt() == ""
    fixture.memory.list.assert_not_awaited()

    assert await fixture.refresh(after_compaction=False)
    assert "boundary snapshot design" in await fixture.prompt()
    fixture.toolkit_state.save.assert_awaited_once()
