"""Historical Memory boundary snapshot contract tests."""

import datetime

import pytest
from pydantic import ValidationError

from azents.core.historical_memory_snapshot import (
    HistoricalMemorySnapshotEntry,
    MemoryContextSnapshotState,
    SavedMemorySnapshotEntry,
)

_NOW = datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC)


def _saved() -> SavedMemorySnapshotEntry:
    return SavedMemorySnapshotEntry(
        memory_id="m" * 32,
        scope="agent",
        name="project-state",
        type="project",
        description_snapshot="Current project state",
        updated_at_snapshot=_NOW,
        vfs_path=f"azents://memory/saved/agent/{'m' * 32}.md",
    )


def _historical() -> HistoricalMemorySnapshotEntry:
    return HistoricalMemorySnapshotEntry(
        source_session_id="s" * 32,
        source_scope="team",
        source_title_snapshot="Prior session",
        source_activity_through=_NOW - datetime.timedelta(hours=7),
        prepared_at=_NOW,
        summary_snapshot="The user approved the bounded design.",
        summary_vfs_path=(f"azents://memory/historical/team/{'s' * 32}/summary.md"),
        source_vfs_path=f"azents://memory/sources/team/{'s' * 32}/session.md",
    )


def test_snapshot_round_trips_typed_entries() -> None:
    """Toolkit State JSON preserves exact boundary and entry fields."""
    snapshot = MemoryContextSnapshotState(
        boundary_head_event_id=None,
        created_at=_NOW,
        saved_entries=[_saved()],
        historical_entries=[_historical()],
    )

    decoded = MemoryContextSnapshotState.model_validate(
        snapshot.model_dump(mode="json")
    )

    assert decoded == snapshot
    assert decoded.schema_version == 1


def test_snapshot_rejects_naive_timestamps_and_non_memory_paths() -> None:
    """Persisted snapshot inputs cannot lose time or namespace identity."""
    with pytest.raises(ValidationError, match="timezone-aware"):
        SavedMemorySnapshotEntry.model_validate(
            {
                **_saved().model_dump(),
                "updated_at_snapshot": datetime.datetime(2026, 10, 1),
            }
        )
    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        HistoricalMemorySnapshotEntry.model_validate(
            {
                **_historical().model_dump(),
                "summary_vfs_path": "azents://skills/not-memory.md",
            }
        )
