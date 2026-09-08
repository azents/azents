"""Session Workspace Project operation repository data."""

import dataclasses

from azents.repos.session_workspace_project.data import SessionWorkspaceProject


@dataclasses.dataclass(frozen=True)
class ProjectDatabaseContext:
    """Detached Session and Agent identity for external Project preflight work."""

    agent_id: str
    session_id: str


@dataclasses.dataclass(frozen=True)
class ProjectMutationResult:
    """Committed Project mutation and its detached Agent identity."""

    project: SessionWorkspaceProject
    context: ProjectDatabaseContext


@dataclasses.dataclass(frozen=True)
class ProjectContextUnavailable:
    """The current Session or membership cannot authorize the operation."""


@dataclasses.dataclass(frozen=True)
class ProjectBindingUnavailable:
    """Current Runtime target no longer matches Session folder authority."""


@dataclasses.dataclass(frozen=True)
class ProjectConflict:
    """An exact Project path is already registered in the Session context."""

    project: SessionWorkspaceProject


@dataclasses.dataclass(frozen=True)
class ProjectCleanupInProgress:
    """An overlapping cleanup claim owns the requested path."""

    path: str


@dataclasses.dataclass(frozen=True)
class ProjectMissing:
    """The selected Project does not exist in the authorized context."""
