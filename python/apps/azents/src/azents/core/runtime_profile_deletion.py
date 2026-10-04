"""Canonical shared runtime profile deletion contracts."""

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkspaceRuntimeProfileDeletion:
    """Bounded impact from one committed Workspace Profile deletion."""

    profile_id: str
    cleared_workspace_default: bool
    cleared_agent_count: int
    affected_running_runtime_count: int
    superseded_recreation_operation_count: int
