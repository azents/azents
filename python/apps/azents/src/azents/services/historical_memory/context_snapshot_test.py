"""Real database boundary refresh, exact old-revision filtering and live separation."""

import datetime
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from uuid6 import uuid7

from azents.core.enums import EventKind
from azents.core.historical_memory import HistoricalMemoryCompletion
from azents.core.historical_memory_snapshot import MemoryContextSnapshotState
from azents.engine.events.types import CompactionSummaryPayload
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.event import RDBEvent
from azents.rdb.models.toolkit_state import RDBToolkitState
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.historical_memory import HistoricalMemoryRepository
from azents.repos.historical_memory_consolidation.authority import (
    ConsolidationAuthorityBusyError,
    ConsolidationDeadlineError,
)
from azents.repos.memory import MemoryRepository
from azents.repos.memory.data import MemoryCreate, MemoryScope
from azents.repos.memory_context_snapshot import MemoryContextSnapshotRepository
from azents.repos.memory_vfs.data import MemoryVfsAuthority
from azents.repos.memory_vfs.repository import MemoryVfsRepository
from azents.repos.message import MessageRepository
from azents.repos.toolkit_state import ToolkitStateConflictError, ToolkitStateRepository
from azents.services.historical_memory.context_snapshot import (
    MemoryContextSnapshotService,
)
from azents.testing.consolidated_context import publish_context_overview
from azents.testing.consolidation import ConsolidationCorpus, seed_consolidation_corpus


def _service(manager: SessionManager[WriteSession]) -> MemoryContextSnapshotService:
    return MemoryContextSnapshotService(
        MemoryContextSnapshotRepository(
            HistoricalMemoryRepository(manager),
            MemoryRepository(),
            MessageRepository(),
            ToolkitStateRepository(),
            manager,
            manager,
        )
    )


def _markdown(corpus: ConsolidationCorpus, text: str) -> str:
    return (
        f"## Historical Context\n{text}\n\n## Source Routes\n"
        f"- azents://memory/historical/team/{corpus.team_source}/summary.md"
        " — Synthetic details\n"
    )


async def _change(
    manager: SessionManager[WriteSession], corpus: ConsolidationCorpus
) -> None:
    now = datetime.datetime.now(datetime.UTC)
    result = await HistoricalMemoryRepository(manager).publish_completed(
        source_session_id=corpus.team_source,
        completion=HistoricalMemoryCompletion(
            source_activity_at=now,
            source_tail_event_id=uuid7().hex,
            prepared_at=now,
            source_title_snapshot="New canonical source",
            summary="New generation pending",
        ),
    )
    assert result is not None


async def _state(
    manager: SessionManager[WriteSession], session_id: str
) -> RDBToolkitState:
    async with manager() as session:
        row = await session.read_session.scalar(
            sa.select(RDBToolkitState).where(
                RDBToolkitState.session_id == session_id,
                RDBToolkitState.toolkit_namespace == "memory",
                RDBToolkitState.state_name == "context_snapshot",
            )
        )
        assert row is not None
        return row


async def test_ordinary_turn_retains_exact_old_bytes_then_next_run_selects_latest(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    manager = rdb_session_manager
    corpus = await seed_consolidation_corpus(manager)
    service = _service(manager)
    old = await publish_context_overview(
        manager, key=corpus.team, markdown=_markdown(corpus, "Old selected text")
    )
    assert await service.refresh_snapshot(
        session_id=corpus.team_source, after_compaction=False
    )
    selected = await _state(manager, corpus.team_source)
    snapshot = MemoryContextSnapshotState.model_validate(selected.state_json)
    assert snapshot.historical_entries[0].revision_id == old
    await _change(manager, corpus)
    new = await publish_context_overview(
        manager, key=corpus.team, markdown=_markdown(corpus, "New latest text")
    )
    assert new != old
    prompt = await service.prompt_for_turn(session_id=corpus.team_source)
    assert "Old selected text" in prompt and "New latest text" not in prompt
    assert (await _state(manager, corpus.team_source)).version == selected.version
    live = await MemoryVfsRepository(manager).get_consolidated(
        MemoryVfsAuthority(
            root_session_id=corpus.team_source,
            agent_id=corpus.team.agent_id,
            workspace_id=corpus.team.workspace_id,
            associated_user_id=None,
            memory_enabled=True,
        ),
        scope="team",
        max_bytes=20000,
    )
    assert live is not None
    assert live.entry.revision_id == new
    assert "New latest text" in live.entry.rendered_block
    assert "Old selected text" not in live.entry.rendered_block
    assert (await _state(manager, corpus.team_source)).version == selected.version
    assert "Old selected text" in await service.prompt_for_turn(
        session_id=corpus.team_source
    )
    assert await service.refresh_snapshot(
        session_id=corpus.team_source, after_compaction=False
    )
    prompt = await service.prompt_for_turn(session_id=corpus.team_source)
    assert "New latest text" in prompt and "Old selected text" not in prompt
    stable = await _state(manager, corpus.team_source)
    assert await service.refresh_snapshot(
        session_id=corpus.team_source, after_compaction=False
    )
    assert (await _state(manager, corpus.team_source)).version == stable.version


@pytest.mark.parametrize("observe_old_selection", [False, True])
async def test_identical_clean_revision_after_denial_changes_native_binding(
    rdb_session_manager: SessionManager[WriteSession],
    observe_old_selection: bool,
) -> None:
    """Unobserved revoke/restore cannot revive old opaque state by equal bytes."""
    manager = rdb_session_manager
    corpus = await seed_consolidation_corpus(manager)
    service = _service(manager)
    markdown = _markdown(corpus, "Same regenerated authorized context")
    old = await publish_context_overview(manager, key=corpus.team, markdown=markdown)
    assert await service.refresh_snapshot(
        session_id=corpus.personal_source,
        after_compaction=False,
    )
    before = await service.context_for_turn(session_id=corpus.personal_source)
    previous = MemoryContextSnapshotState.model_validate(
        (await _state(manager, corpus.personal_source)).state_json
    )
    async with manager() as session:
        sources = AgentSessionRepository()
        await sources.archive(
            session, corpus.team_source, ended_at=datetime.datetime.now(datetime.UTC)
        )
        await sources.restore_tree(
            session,
            root_session_id=corpus.team_source,
            session_ids=[corpus.team_source],
        )
    new = await publish_context_overview(manager, key=corpus.team, markdown=markdown)
    assert new != old
    # No foreground reader observed the denied interval. Old selected authority
    # still cannot be authorized by the clean current pointer.
    if observe_old_selection:
        denied = await service.context_for_turn(session_id=corpus.personal_source)
        assert "Same regenerated authorized context" not in denied.text
        assert denied.native_replay_context != before.native_replay_context
    assert await service.refresh_snapshot(
        session_id=corpus.personal_source,
        after_compaction=False,
    )
    after = await service.context_for_turn(session_id=corpus.personal_source)
    current = MemoryContextSnapshotState.model_validate(
        (await _state(manager, corpus.personal_source)).state_json
    )
    assert after.text == before.text
    assert after.native_replay_context != before.native_replay_context
    assert current.historical_entries[0].revision_id == new
    assert current.created_at >= previous.created_at
    stable = await service.context_for_turn(session_id=corpus.personal_source)
    assert stable == after
    selected_state = await _state(manager, corpus.personal_source)
    assert await service.refresh_snapshot(
        session_id=corpus.personal_source,
        after_compaction=False,
    )
    unchanged_state = await _state(manager, corpus.personal_source)
    assert unchanged_state.version == selected_state.version
    assert (
        MemoryContextSnapshotState.model_validate(unchanged_state.state_json).created_at
        == current.created_at
    )


async def test_empty_current_outcome_does_not_rewrite_still_authorized_old_snapshot(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    manager = rdb_session_manager
    corpus = await seed_consolidation_corpus(manager)
    service = _service(manager)
    await publish_context_overview(
        manager, key=corpus.team, markdown=_markdown(corpus, "Useful old context")
    )
    assert await service.refresh_snapshot(
        session_id=corpus.team_source, after_compaction=False
    )
    await _change(manager, corpus)
    await publish_context_overview(
        manager, key=corpus.team, markdown="## Historical Context\n\n## Source Routes\n"
    )
    assert "Useful old context" in await service.prompt_for_turn(
        session_id=corpus.team_source
    )
    assert await service.refresh_snapshot(
        session_id=corpus.team_source, after_compaction=False
    )
    assert "Useful old context" not in await service.prompt_for_turn(
        session_id=corpus.team_source
    )


async def test_source_denial_restore_suppresses_whole_selected_team_but_keeps_saved(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    manager = rdb_session_manager
    corpus = await seed_consolidation_corpus(manager)
    service = _service(manager)
    async with manager() as session:
        await MemoryRepository().create(
            session,
            agent_id=corpus.team.agent_id,
            user_id=None,
            create=MemoryCreate(
                scope=MemoryScope.AGENT,
                type="project",
                name="Independent knowledge",
                description="Saved survives source denial",
                content="Synthetic Saved body",
            ),
        )
    await publish_context_overview(
        manager, key=corpus.team, markdown=_markdown(corpus, "Denied context")
    )
    # The personal root can use Team independently of its own private unit.
    assert await service.refresh_snapshot(
        session_id=corpus.personal_source,
        after_compaction=False,
    )
    async with manager() as session:
        repository = AgentSessionRepository()
        await repository.archive(
            session, corpus.team_source, ended_at=datetime.datetime.now(datetime.UTC)
        )
        await repository.restore_tree(
            session,
            root_session_id=corpus.team_source,
            session_ids=[corpus.team_source],
        )
    prompt = await service.prompt_for_turn(session_id=corpus.personal_source)
    assert "Denied context" not in prompt
    assert "Saved survives source denial" in prompt


@pytest.mark.parametrize("foreign", [False, True])
async def test_uncommitted_or_foreign_compaction_cannot_reselect(
    rdb_session_manager: SessionManager[WriteSession],
    foreign: bool,
) -> None:
    manager = rdb_session_manager
    corpus = await seed_consolidation_corpus(manager)
    service = _service(manager)
    assert await service.refresh_snapshot(
        session_id=corpus.team_source, after_compaction=False
    )
    async with manager() as session:
        row = await session.read_session.get(RDBAgentSession, corpus.team_source)
        assert row is not None
        if foreign:
            event = RDBEvent(
                session_id=corpus.personal_source,
                kind=EventKind.COMPACTION_SUMMARY,
                payload={"compaction_id": "foreign", "content": "Synthetic"},
            )
            session.write_session.add(event)
            await session.write_session.flush()
            row.model_input_head_event_id = event.id
        else:
            row.model_input_head_event_id = uuid7().hex
    assert not await service.refresh_snapshot(
        session_id=corpus.team_source, after_compaction=True
    )
    assert await service.prompt_for_turn(session_id=corpus.team_source) == ""


async def test_compaction_rebinds_identical_content_and_preserves_creation_time(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    manager = rdb_session_manager
    corpus = await seed_consolidation_corpus(manager)
    service = _service(manager)
    await publish_context_overview(
        manager, key=corpus.team, markdown=_markdown(corpus, "Stable whole document")
    )
    assert await service.refresh_snapshot(
        session_id=corpus.team_source, after_compaction=False
    )
    before = MemoryContextSnapshotState.model_validate(
        (await _state(manager, corpus.team_source)).state_json
    )
    # A notification before commit leaves the unchanged head and bytes alone.
    assert await service.refresh_snapshot(
        session_id=corpus.team_source, after_compaction=True
    )
    async with manager() as session:
        event = RDBEvent(
            session_id=corpus.team_source,
            kind=EventKind.COMPACTION_SUMMARY,
            payload=CompactionSummaryPayload(
                compaction_id="synthetic", content="Unrelated topic"
            ).model_dump(mode="json"),
        )
        session.write_session.add(event)
        await session.write_session.flush()
        root = await session.read_session.get(RDBAgentSession, corpus.team_source)
        assert root is not None
        root.model_input_head_event_id = event.id
    assert await service.refresh_snapshot(
        session_id=corpus.team_source, after_compaction=True
    )
    after = MemoryContextSnapshotState.model_validate(
        (await _state(manager, corpus.team_source)).state_json
    )
    assert after.created_at == before.created_at
    assert after.historical_entries == before.historical_entries
    assert after.boundary_head_event_id != before.boundary_head_event_id


async def test_invalid_snapshots_only_refresh_at_explicit_boundary(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    manager = rdb_session_manager
    corpus = await seed_consolidation_corpus(manager)
    service = _service(manager)
    assert await service.prompt_for_turn(session_id=corpus.team_source) == ""
    assert await service.refresh_snapshot(
        session_id=corpus.team_source, after_compaction=False
    )
    for version, payload in [(1, {}), (2, {"kind": "old"}), (99, {})]:
        async with manager() as session:
            row = await session.read_session.get(
                RDBToolkitState, (await _state(manager, corpus.team_source)).id
            )
            assert row is not None
            row.schema_version = version
            row.state_json = payload
        assert await service.prompt_for_turn(session_id=corpus.team_source) == ""
        assert await service.refresh_snapshot(
            session_id=corpus.team_source,
            after_compaction=False,
        )
        assert (await _state(manager, corpus.team_source)).schema_version == 2


async def test_refresh_cas_conflict_and_memory_disablement_do_not_claim_preparation(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    manager = rdb_session_manager
    corpus = await seed_consolidation_corpus(manager)
    service = _service(manager)
    toolkit = AsyncMock(spec=ToolkitStateRepository)
    toolkit.get.return_value = None
    toolkit.save.side_effect = ToolkitStateConflictError()
    service.repository.toolkit_state_repository = toolkit
    assert not await service.refresh_snapshot(
        session_id=corpus.team_source, after_compaction=False
    )
    async with manager() as session:
        agent = await session.read_session.get(RDBAgent, corpus.team.agent_id)
        assert agent is not None
        agent.memory_enabled = False
    assert not await service.refresh_snapshot(
        session_id=corpus.team_source, after_compaction=False
    )
    assert await service.prompt_for_turn(session_id=corpus.team_source) == ""


@pytest.mark.parametrize(
    "failure", [ConsolidationAuthorityBusyError, ConsolidationDeadlineError]
)
async def test_unconfirmed_authority_omits_context_without_failing_conversation(
    rdb_session_manager: SessionManager[WriteSession],
    failure: type[ConsolidationAuthorityBusyError] | type[ConsolidationDeadlineError],
) -> None:
    repository = AsyncMock(spec=MemoryContextSnapshotRepository)
    repository.prompt_for_turn.side_effect = failure("Expected authority failure")
    repository.refresh_snapshot.side_effect = failure("Expected authority failure")
    service = MemoryContextSnapshotService(repository)
    assert await service.prompt_for_turn(session_id="a" * 32) == ""
    assert not await service.refresh_snapshot(
        session_id="a" * 32,
        after_compaction=False,
    )
    repository.prompt_for_turn.side_effect = RuntimeError("Unexpected failure")
    with pytest.raises(RuntimeError, match="Unexpected"):
        await service.prompt_for_turn(session_id="a" * 32)
