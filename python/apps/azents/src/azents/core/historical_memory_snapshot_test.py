"""Strict aggregate boundary snapshot contracts and whole-unit budgets."""

import datetime

import pytest
from pydantic import ValidationError

from azents.core.historical_memory_consolidation import ConsolidationScope
from azents.core.historical_memory_context import build_memory_context_snapshot
from azents.core.historical_memory_snapshot import (
    ConsolidatedMemorySnapshotEntry,
    MemoryContextSnapshotState,
    SavedMemorySnapshotEntry,
)
from azents.testing.consolidated_context import CONTEXT_FIXTURE_TIME, context_entry


def test_snapshot_round_trips_exact_new_kind_and_whole_revision() -> None:
    entry = context_entry(
        scope=ConsolidationScope.TEAM, text="Approved context 한글", exact_bytes=None
    )
    snapshot = build_memory_context_snapshot(
        boundary_head_event_id=None,
        created_at=CONTEXT_FIXTURE_TIME,
        saved_entries=[],
        historical_entries=[entry],
    )
    assert (
        MemoryContextSnapshotState.model_validate(snapshot.model_dump(mode="json"))
        == snapshot
    )
    assert snapshot.schema_version == 2 and snapshot.kind == "consolidated_memory"


@pytest.mark.parametrize("version", [0, 1, 3, 99])
def test_snapshot_rejects_old_and_future_versions(version: int) -> None:
    with pytest.raises(ValidationError):
        MemoryContextSnapshotState.model_validate(
            {
                "kind": "consolidated_memory",
                "schema_version": version,
                "boundary_head_event_id": None,
                "created_at": CONTEXT_FIXTURE_TIME,
                "saved_entries": [],
                "historical_entries": [],
            }
        )


def test_old_source_shape_is_not_reinterpreted_as_new_kind() -> None:
    with pytest.raises(ValidationError):
        MemoryContextSnapshotState.model_validate(
            {
                "schema_version": 1,
                "boundary_head_event_id": None,
                "created_at": CONTEXT_FIXTURE_TIME,
                "saved_entries": [],
                "historical_entries": [],
            }
        )


def test_snapshot_rejects_repeated_scope_and_oversized_complete_blocks() -> None:
    entry = context_entry(
        scope=ConsolidationScope.TEAM, text="context", exact_bytes=10000
    )
    assert len(entry.rendered_block.encode()) == 10000
    with pytest.raises(ValidationError, match="independent budget"):
        ConsolidatedMemorySnapshotEntry.model_validate(
            {
                **entry.model_dump(),
                "rendered_block": entry.rendered_block + "x",
            }
        )
    with pytest.raises(ValidationError, match="repeats a scope"):
        build_memory_context_snapshot(
            boundary_head_event_id=None,
            created_at=CONTEXT_FIXTURE_TIME,
            saved_entries=[],
            historical_entries=[entry, entry],
        )
    with pytest.raises(ValidationError, match="timezone-aware"):
        ConsolidatedMemorySnapshotEntry.model_validate(
            {
                **entry.model_dump(),
                "published_at": datetime.datetime(2026, 10, 3),
            }
        )


def test_saved_contract_still_rejects_non_memory_paths() -> None:
    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        SavedMemorySnapshotEntry(
            memory_id="a" * 32,
            scope="agent",
            name="name",
            type="project",
            description_snapshot="description",
            updated_at_snapshot=CONTEXT_FIXTURE_TIME,
            vfs_path="azents://skills/other.md",
        )
