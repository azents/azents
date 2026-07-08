"""Session Git worktree shared enum types."""

from sqlalchemy.dialects.postgresql import ENUM

from azents.core.enums import (
    SessionGitWorktreeBranchCreatedBy,
    SessionGitWorktreeStatus,
)


def _session_git_worktree_status_values(
    enum_cls: type[SessionGitWorktreeStatus],
) -> list[str]:
    """Return SessionGitWorktreeStatus enum values stored in the DB."""
    return [v.value for v in enum_cls]


def _session_git_worktree_branch_created_by_values(
    enum_cls: type[SessionGitWorktreeBranchCreatedBy],
) -> list[str]:
    """Return SessionGitWorktreeBranchCreatedBy enum values stored in the DB."""
    return [v.value for v in enum_cls]


session_git_worktree_status_enum = ENUM(
    SessionGitWorktreeStatus,
    name="session_git_worktree_status",
    create_type=False,
    values_callable=_session_git_worktree_status_values,
)
session_git_worktree_branch_created_by_enum = ENUM(
    SessionGitWorktreeBranchCreatedBy,
    name="session_git_worktree_branch_created_by",
    create_type=False,
    values_callable=_session_git_worktree_branch_created_by_values,
)
