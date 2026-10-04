"""Detached outcomes for specific completed worktree operations."""

from dataclasses import dataclass
from enum import Enum

from azents.core.action_execution_data import ActionExecution
from azents.core.agent_session_data import AgentSession, SessionAgent
from azents.core.session_workspace_project import SessionWorkspaceProject
from azents.repos.agent.data import Agent
from azents.repos.session_git_worktree.data import SessionGitWorktree


class PreviewAccess(Enum):
    ALLOWED = "allowed"
    AGENT_NOT_FOUND = "agent_not_found"
    ACCESS_DENIED = "access_denied"


class CleanupDecision(Enum):
    SESSION_NOT_FOUND = "session_not_found"
    ACCESS_DENIED = "access_denied"
    SUBAGENT_READ_ONLY = "subagent_read_only"
    NOT_FOUND = "not_found"
    NO_CLEANUP = "no_cleanup"
    CLEANUP_PENDING = "cleanup_pending"


@dataclass(frozen=True)
class WorktreeContext:
    agent: Agent | None
    agent_session: AgentSession | None
    session_agent: SessionAgent | None
    source_project: SessionWorkspaceProject | None


@dataclass(frozen=True)
class StartedCleanup:
    agent_session: AgentSession | None
    context_runtime_id: str | None
    execution: ActionExecution


@dataclass(frozen=True)
class RemovalIntent:
    allocation: SessionGitWorktree
    project: SessionWorkspaceProject


@dataclass(frozen=True)
class TargetChoice:
    allocation: SessionGitWorktree | None
    path_exists: bool
    branch_exists: bool
    claim_exists: bool


@dataclass(frozen=True)
class CompensatedProject:
    agent_session: AgentSession
    project: SessionWorkspaceProject


@dataclass(frozen=True)
class ArchiveCleanupPreparation:
    allocations: list[SessionGitWorktree]
    eligible_allocations: list[SessionGitWorktree]
    rejected_allocations: list[SessionGitWorktree]


class RemovalAuthorityChanged(ValueError):
    """Expected rejection retaining the observed allocation for failure settlement."""

    def __init__(self, *, reason: str, allocation: SessionGitWorktree | None) -> None:
        super().__init__(reason)
        self.allocation = allocation


class RemovalClaimConflict(RuntimeError):
    """Path claim conflict retaining the observed allocation for settlement."""

    def __init__(self, *, allocation: SessionGitWorktree) -> None:
        super().__init__("Another destructive operation currently owns this path.")
        self.allocation = allocation
