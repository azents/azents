"""Detached outcomes for completed Workspace operations."""

import dataclasses


@dataclasses.dataclass(frozen=True)
class WorkspaceOwnerCreation:
    """Committed Workspace identity after its initial Owner membership exists."""

    workspace_handle: str
