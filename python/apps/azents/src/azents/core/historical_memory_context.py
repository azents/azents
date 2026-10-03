"""Whole-document Memory boundary assembly without ranking or truncation."""

import dataclasses
import datetime
import hashlib
import json
from collections.abc import Collection, Sequence
from textwrap import dedent

from azents.core.historical_memory_snapshot import (
    ConsolidatedMemorySnapshotEntry,
    MemoryContextSnapshotState,
    SavedMemorySnapshotEntry,
)


@dataclasses.dataclass(frozen=True)
class MemoryContextPrompt:
    """Atomic visible text and exact admitted Historical replay compatibility."""

    text: str
    native_replay_context: str


def prepare_memory_context_prompt(
    snapshot: MemoryContextSnapshotState | None,
) -> MemoryContextPrompt:
    """Use already authorized identities; this digest grants no source access."""
    identities = (
        sorted(
            (entry.unit_id, entry.revision_id) for entry in snapshot.historical_entries
        )
        if snapshot is not None
        else []
    )
    digest = hashlib.sha256(
        json.dumps(identities, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return MemoryContextPrompt(
        text=render_memory_context_snapshot(snapshot) if snapshot is not None else "",
        native_replay_context=f"memory-selection-{digest}",
    )


_READ_GUIDANCE = dedent("""\
    ### Saved Memory Use Rules

    Saved Memory is independently managed knowledge. Its selected index contains
    lookup references rather than full entry bodies. Read a permitted exact path
    when the entry can materially change the answer.

    Current instructions and verified current evidence take precedence.""")


def build_memory_context_snapshot(
    *,
    boundary_head_event_id: str | None,
    created_at: datetime.datetime,
    saved_entries: Sequence[SavedMemorySnapshotEntry],
    historical_entries: Sequence[ConsolidatedMemorySnapshotEntry],
) -> MemoryContextSnapshotState:
    """Keep complete independently bounded documents and a separate Saved index."""
    ordered_saved = sorted(
        saved_entries,
        key=lambda entry: (
            entry.type.casefold(),
            entry.name.casefold(),
            entry.memory_id,
        ),
    )
    ordered_historical = sorted(
        historical_entries, key=lambda entry: entry.unit.scope.value
    )
    return MemoryContextSnapshotState(
        kind="consolidated_memory",
        schema_version=2,
        boundary_head_event_id=boundary_head_event_id,
        created_at=created_at,
        saved_entries=ordered_saved,
        historical_entries=ordered_historical,
    )


def filter_memory_context_snapshot(
    snapshot: MemoryContextSnapshotState,
    *,
    available_saved_ids: Collection[str],
    available_revision_ids: Collection[str],
) -> MemoryContextSnapshotState:
    """Remove entire denied units without replacement, rewriting or reselection."""
    return snapshot.model_copy(
        update={
            "saved_entries": [
                entry
                for entry in snapshot.saved_entries
                if entry.memory_id in available_saved_ids
            ],
            "historical_entries": [
                entry
                for entry in snapshot.historical_entries
                if entry.revision_id in available_revision_ids
            ],
        }
    )


def render_memory_context_snapshot(snapshot: MemoryContextSnapshotState) -> str:
    """Concatenate canonical Historical envelopes with no additional framing."""
    parts = [
        "## Memories",
        "",
        "Memory persists across conversations. The entries below were selected at "
        "this Session's current context boundary.",
    ]
    if snapshot.saved_entries:
        parts.extend(["", "### Saved Memory"])
        current_type: str | None = None
        for entry in snapshot.saved_entries:
            if entry.type != current_type:
                current_type = entry.type
                parts.extend(["", f"#### {entry.type.title()}"])
            parts.extend(
                [
                    f"- **{entry.name}** [{entry.scope}] — "
                    f"{entry.description_snapshot}",
                    f"  Path: `{entry.vfs_path}`",
                ]
            )
    parts.extend(["", _READ_GUIDANCE, ""])
    prefix = "\n".join(parts)
    historical = "".join(entry.rendered_block for entry in snapshot.historical_entries)
    return prefix + historical


def render_live_consolidated(entry: ConsolidatedMemorySnapshotEntry) -> str:
    """Explicit lookup shows current provenance without changing a boundary."""
    return (
        f"Revision: {entry.revision_id}\n"
        f"Published: {entry.published_at.isoformat()}\n"
        f"Location: azents://memory/consolidated/{entry.unit.scope.value}/summary.md\n\n"
        f"{entry.rendered_block}"
    )
