"""Pure Skill projection state models and transformations."""

import dataclasses
import datetime
import hashlib
import json
import posixpath
from pathlib import PurePosixPath
from typing import Any, Literal

from azcommon.uuid import uuid7
from pydantic import Field

from azents.core.enums import AgentSessionRunState
from azents.core.toolkit_state import ToolkitStateModel
from azents.core.vfs import canonicalize_vfs_uri

SKILL_TOOLKIT_NAMESPACE = "skill"
SKILL_TOOLKIT_STATE_NAME = "projection"
SKILL_STATE_SCHEMA_VERSION = 1

SkillSourceKind = Literal["agent", "project_agents", "project_claude", "azents"]
SyncReason = Literal[
    "session_start",
    "run_end",
    "compaction_start",
    "project_change",
    "manual",
]


class SkillProjectionItem(ToolkitStateModel):
    """Projected filesystem Skill item."""

    schema_version: int = SKILL_STATE_SCHEMA_VERSION
    id: str = Field(min_length=1, description="Stable projection-local Skill item ID")
    source_kind: SkillSourceKind = Field(description="Skill source kind")
    project_id: str | None = Field(default=None, description="Project ID")
    project_path: str | None = Field(default=None, description="Project path")
    skill_dir_path: str = Field(
        min_length=1, description="Skill package directory path"
    )
    skill_path: str = Field(min_length=1, description="Exact SKILL.md path")
    slug: str = Field(min_length=1, description="Skill directory slug")
    name: str = Field(min_length=1, description="Skill display name")
    description: str = Field(description="Skill description")
    frontmatter: dict[str, Any] = Field(default_factory=dict)
    body: str = Field(description="Full SKILL.md body")
    content_hash: str = Field(min_length=1, description="SHA-256 content hash")
    source_label: str = Field(min_length=1, description="Compact source label")
    relative_hint: str = Field(min_length=1, description="Compact relative path hint")


class SkillProjectionSnapshot(ToolkitStateModel):
    """One complete Skill projection snapshot."""

    schema_version: int = SKILL_STATE_SCHEMA_VERSION
    revision_id: str = Field(default_factory=lambda: uuid7().hex)
    projection_hash: str = Field(default="", description="Hash of projected items")
    synced_at: str | None = Field(default=None, description="UTC sync timestamp")
    sync_reason: SyncReason | None = Field(default=None, description="Sync reason")
    items: list[SkillProjectionItem] = Field(default_factory=list)


class SkillProjectionState(ToolkitStateModel):
    """Session Skill projection Toolkit State payload."""

    schema_version: int = SKILL_STATE_SCHEMA_VERSION
    latest: SkillProjectionSnapshot = Field(default_factory=SkillProjectionSnapshot)
    active: SkillProjectionSnapshot = Field(default_factory=SkillProjectionSnapshot)


@dataclasses.dataclass(frozen=True)
class SkillProjectInvalidation:
    """Typed Project removal input for one Skill projection state."""

    project_id: str
    project_path: str
    session_run_state: AgentSessionRunState
    revision_id: str
    synced_at: str


def make_skill_project_invalidation(
    *,
    project_id: str,
    project_path: str,
    session_run_state: AgentSessionRunState,
) -> SkillProjectInvalidation:
    """Create time and identity evidence for a pure projection transformation."""
    return SkillProjectInvalidation(
        project_id=project_id,
        project_path=project_path,
        session_run_state=session_run_state,
        revision_id=uuid7().hex,
        synced_at=datetime.datetime.now(datetime.UTC).isoformat(),
    )


def invalidate_skill_project(
    state: SkillProjectionState,
    invalidation: SkillProjectInvalidation,
) -> SkillProjectionState:
    """Remove one Project's items while preserving active-run snapshot semantics."""
    latest = _filter_project(state.latest, invalidation)
    active = (
        _filter_project(state.active, invalidation)
        if invalidation.session_run_state is AgentSessionRunState.IDLE
        else state.active
    )
    return state.model_copy(update={"latest": latest, "active": active})


def _filter_project(
    snapshot: SkillProjectionSnapshot,
    invalidation: SkillProjectInvalidation,
) -> SkillProjectionSnapshot:
    items = [
        item
        for item in snapshot.items
        if item.project_id != invalidation.project_id
        and item.project_path != invalidation.project_path
    ]
    if len(items) == len(snapshot.items):
        return snapshot
    return SkillProjectionSnapshot(
        revision_id=invalidation.revision_id,
        projection_hash=_projection_hash(items),
        synced_at=invalidation.synced_at,
        sync_reason="project_change",
        items=items,
    )


def resolve_active_skill(
    state: SkillProjectionState,
    *,
    skill_path: str,
) -> SkillProjectionItem | None:
    """Resolve one exact normalized path from the active projection."""
    normalized = _normalize_path(skill_path)
    for item in state.active.items:
        if _normalize_path(item.skill_path) == normalized:
            return item
    return None


def _normalize_path(path: str) -> str:
    if path.startswith("azents://"):
        return canonicalize_vfs_uri(path)
    return PurePosixPath(posixpath.normpath(path)).as_posix()


def _projection_hash(items: list[SkillProjectionItem]) -> str:
    payload = [
        {
            "source_kind": item.source_kind,
            "project_id": item.project_id,
            "project_path": item.project_path,
            "skill_path": item.skill_path,
            "content_hash": item.content_hash,
        }
        for item in items
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
