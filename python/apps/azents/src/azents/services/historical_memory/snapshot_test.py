"""Independent 10k documents, exact 20k composition and whole-unit filtering."""

import pytest

from azents.core.historical_memory_consolidation import ConsolidationScope
from azents.core.historical_memory_context import (
    build_memory_context_snapshot,
    filter_memory_context_snapshot,
    render_memory_context_snapshot,
)
from azents.core.historical_memory_snapshot import SavedMemorySnapshotEntry
from azents.testing.consolidated_context import CONTEXT_FIXTURE_TIME, context_entry


@pytest.mark.parametrize(
    "team_bytes,user_bytes", [(10000, 10000), (10000, 600), (600, 10000)]
)
def test_complete_multilingual_documents_have_independent_budgets(
    team_bytes: int, user_bytes: int
) -> None:
    team = context_entry(
        scope=ConsolidationScope.TEAM, text="Team 한글 🧠", exact_bytes=team_bytes
    )
    user = context_entry(
        scope=ConsolidationScope.USER, text="User 日本語 🧠", exact_bytes=user_bytes
    )
    snapshot = build_memory_context_snapshot(
        boundary_head_event_id=None,
        created_at=CONTEXT_FIXTURE_TIME,
        saved_entries=[],
        historical_entries=[user, team],
    )
    assert snapshot.historical_entries == [team, user]
    rendered = render_memory_context_snapshot(snapshot)
    historical = team.rendered_block + user.rendered_block
    assert rendered.endswith(historical)
    assert "Historical" not in rendered.removesuffix(historical)
    assert len(historical.encode()) == team_bytes + user_bytes <= 20000
    assert rendered.count("HISTORICAL MEMORY DATA BEGINS") == 2
    assert team.rendered_block in rendered and user.rendered_block in rendered


def test_single_unit_does_not_borrow_missing_peer_budget() -> None:
    entry = context_entry(
        scope=ConsolidationScope.TEAM, text="single", exact_bytes=10000
    )
    snapshot = build_memory_context_snapshot(
        boundary_head_event_id=None,
        created_at=CONTEXT_FIXTURE_TIME,
        saved_entries=[],
        historical_entries=[entry],
    )
    assert render_memory_context_snapshot(snapshot).endswith(entry.rendered_block)
    assert len(entry.rendered_block.encode()) == 10000


def test_filter_removes_whole_denied_unit_without_replacement_or_rewriting() -> None:
    team = context_entry(
        scope=ConsolidationScope.TEAM, text="Team boundary", exact_bytes=None
    )
    user = context_entry(
        scope=ConsolidationScope.USER, text="Personal boundary", exact_bytes=None
    )
    saved = SavedMemorySnapshotEntry(
        memory_id="f" * 32,
        scope="agent",
        name="Current project",
        type="project",
        description_snapshot="Current independent knowledge",
        updated_at_snapshot=CONTEXT_FIXTURE_TIME,
        vfs_path=f"azents://memory/saved/agent/{'f' * 32}.md",
    )
    snapshot = build_memory_context_snapshot(
        boundary_head_event_id=None,
        created_at=CONTEXT_FIXTURE_TIME,
        saved_entries=[saved],
        historical_entries=[team, user],
    )
    filtered = filter_memory_context_snapshot(
        snapshot,
        available_saved_ids={saved.memory_id},
        available_revision_ids={user.revision_id},
    )
    assert filtered.historical_entries == [user]
    assert filtered.saved_entries == [saved]
    assert filtered.created_at == snapshot.created_at
    assert "Team boundary" not in render_memory_context_snapshot(filtered)
    assert "Personal boundary" in render_memory_context_snapshot(filtered)
    assert "Current independent knowledge" in render_memory_context_snapshot(filtered)
