"""Defining detached Runtime management contracts."""

import dataclasses

from azents.core.runtime_profile import RuntimeProfileCompatibility
from azents.core.runtime_provider_data import RuntimeProvider
from azents.repos.runtime_profile.data import (
    RuntimeInfrastructureProfile,
    WorkspaceRuntimeProfile,
)


@dataclasses.dataclass(frozen=True)
class WorkspaceRuntimeProfileProjection:
    """Workspace Profile plus current exact-reference availability."""

    profile: WorkspaceRuntimeProfile
    infrastructure_profile: RuntimeInfrastructureProfile
    provider: RuntimeProvider
    available: bool
    reason_code: str | None
    compatibility: RuntimeProfileCompatibility
    capability_revision_id: str | None


@dataclasses.dataclass(frozen=True)
class SelectableInfrastructureProfileProjection:
    """One exact Provider/Profile option available to a Workspace."""

    profile: RuntimeInfrastructureProfile
    provider: RuntimeProvider
    compatibility: RuntimeProfileCompatibility
    capability_revision_id: str


@dataclasses.dataclass(frozen=True)
class WorkspaceRuntimeProfileDefaultProjection:
    """Workspace default and its current availability projection."""

    runtime_profile_id: str | None
    version: int
    profile: WorkspaceRuntimeProfileProjection | None


@dataclasses.dataclass
class RuntimeProfileWorkspaceUnavailable(Exception):
    """One bounded Workspace Runtime Profile failure."""

    code: str
    message: str
    current_profile: WorkspaceRuntimeProfile | None = None

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)


@dataclasses.dataclass(frozen=True)
class WorkspaceRuntimeProfileReplacementResult:
    """Committed Profile projection and terminal-policy invalidation decision."""

    projection: WorkspaceRuntimeProfileProjection
    terminal_changed: bool
