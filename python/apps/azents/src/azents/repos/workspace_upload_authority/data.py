"""Database authorization projections for Agent Workspace uploads."""

import dataclasses

from azents.core.enums import WorkspaceUserRole
from azents.repos.agent.data import Agent


@dataclasses.dataclass(frozen=True)
class WorkspaceUploadRequesterAuthority:
    """Authorized Agent and Workspace membership projection."""

    agent: Agent
    workspace_user_id: str
    role: WorkspaceUserRole


@dataclasses.dataclass(frozen=True)
class WorkspaceUploadRequesterAgentUnavailable:
    """Requested Agent is unavailable to the requester."""


@dataclasses.dataclass(frozen=True)
class WorkspaceUploadRequesterAccessDenied:
    """Requester lacks Workspace upload authority."""
