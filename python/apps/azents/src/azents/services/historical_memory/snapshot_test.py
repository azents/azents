"""Historical Memory boundary snapshot selection and rendering tests."""

import datetime

from azents.core.historical_memory_snapshot import HistoricalMemorySnapshotCandidate
from azents.repos.memory.data import Memory, MemoryScope
from azents.services.historical_memory.snapshot import (
    build_memory_context_snapshot,
    filter_memory_context_snapshot,
    render_memory_context_snapshot,
)

_NOW = datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC)


def _memory(index: int, *, user: bool = False) -> Memory:
    return Memory(
        id=f"{index:032d}",
        agent_id="a" * 32,
        user_id="u" * 32 if user else None,
        scope=MemoryScope.USER if user else MemoryScope.AGENT,
        type="project",
        name=f"memory-{index}",
        description=f"Description {index}",
        content=f"Content {index}",
        created_at=_NOW,
        updated_at=_NOW + datetime.timedelta(minutes=index),
    )


def _candidate(
    index: int,
    *,
    hours_ago: int,
    title: str,
    summary: str,
    scope: str = "team",
) -> HistoricalMemorySnapshotCandidate:
    return HistoricalMemorySnapshotCandidate.model_validate(
        {
            "source_session_id": f"{index:032d}",
            "source_scope": scope,
            "source_title": title,
            "source_activity_through": _NOW - datetime.timedelta(hours=hours_ago),
            "prepared_at": _NOW - datetime.timedelta(minutes=index),
            "summary": summary,
        }
    )


def test_initial_snapshot_selects_recency_then_presents_chronologically() -> None:
    """Initial selection is newest-first while presentation is oldest-first."""
    snapshot = build_memory_context_snapshot(
        boundary_head_event_id=None,
        created_at=_NOW,
        saved_memories=[_memory(2, user=True), _memory(1)],
        historical_candidates=[
            _candidate(1, hours_ago=20, title="Old", summary="old context"),
            _candidate(2, hours_ago=8, title="New", summary="new context"),
        ],
        topic=None,
    )

    assert [entry.memory_id for entry in snapshot.saved_entries] == [
        f"{1:032d}",
        f"{2:032d}",
    ]
    assert [entry.source_session_id for entry in snapshot.historical_entries] == [
        f"{1:032d}",
        f"{2:032d}",
    ]
    rendered = render_memory_context_snapshot(snapshot)
    assert rendered.index("old context") < rendered.index("new context")
    assert "incomplete, stale, or wrong" in rendered


def test_known_topic_ranks_all_term_match_before_newer_partial_match() -> None:
    """Post-compaction topic relevance precedes source recency."""
    snapshot = build_memory_context_snapshot(
        boundary_head_event_id="h" * 32,
        created_at=_NOW,
        saved_memories=[],
        historical_candidates=[
            _candidate(
                1,
                hours_ago=20,
                title="Historical memory authorization",
                summary="Approved boundary locking",
            ),
            _candidate(
                2,
                hours_ago=8,
                title="Historical memory",
                summary="Recent unrelated implementation",
            ),
        ],
        topic="historical authorization",
        historical_budget_bytes=450,
    )

    assert [entry.source_session_id for entry in snapshot.historical_entries] == [
        f"{1:032d}"
    ]


def test_snapshot_packs_only_complete_groups_and_deduplicates_body_rendering() -> None:
    """Identical normalized bodies render once with every source dependency."""
    duplicate = "Same   historical\naccount"
    snapshot = build_memory_context_snapshot(
        boundary_head_event_id=None,
        created_at=_NOW,
        saved_memories=[],
        historical_candidates=[
            _candidate(1, hours_ago=9, title="First", summary=duplicate),
            _candidate(
                2,
                hours_ago=8,
                title="Second",
                summary="Same historical account",
            ),
        ],
        topic=None,
    )

    rendered = render_memory_context_snapshot(snapshot)
    assert len(snapshot.historical_entries) == 2
    assert rendered.count("Same historical account") == 1
    assert f"Session: {1:032d}" in rendered
    assert f"Session: {2:032d}" in rendered

    excluded = build_memory_context_snapshot(
        boundary_head_event_id=None,
        created_at=_NOW,
        saved_memories=[],
        historical_candidates=[
            _candidate(3, hours_ago=8, title="Large", summary="x" * 500),
        ],
        topic=None,
        historical_budget_bytes=100,
    )
    assert excluded.historical_entries == []


def test_filter_removes_unavailable_entries_without_refresh_or_replacement() -> None:
    """Ordinary turns keep boundary text and only remove denied identities."""
    snapshot = build_memory_context_snapshot(
        boundary_head_event_id=None,
        created_at=_NOW,
        saved_memories=[_memory(1), _memory(2)],
        historical_candidates=[
            _candidate(1, hours_ago=9, title="First", summary="first snapshot"),
            _candidate(2, hours_ago=8, title="Second", summary="second snapshot"),
        ],
        topic=None,
    )

    filtered = filter_memory_context_snapshot(
        snapshot,
        available_saved_ids={f"{1:032d}"},
        available_historical_ids={f"{2:032d}"},
    )

    assert [entry.memory_id for entry in filtered.saved_entries] == [f"{1:032d}"]
    assert [entry.source_session_id for entry in filtered.historical_entries] == [
        f"{2:032d}"
    ]
    assert filtered.saved_entries[0].description_snapshot == "Description 1"
    assert filtered.historical_entries[0].summary_snapshot == "second snapshot"
