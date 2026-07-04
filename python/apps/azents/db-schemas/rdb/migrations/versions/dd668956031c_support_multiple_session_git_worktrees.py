"""support multiple session git worktrees

Revision ID: dd668956031c
Revises: 55a2247574d7
Create Date: 2026-07-04 07:54:31.681012

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "dd668956031c"
down_revision: str | Sequence[str] | None = "55a2247574d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(
        "uq_session_git_worktrees_session_id",
        "session_git_worktrees",
        type_="unique",
    )
    op.add_column(
        "session_git_worktrees",
        sa.Column(
            "session_workspace_project_id",
            sa.String(length=32),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_session_git_worktrees_session_workspace_project_id",
        "session_git_worktrees",
        "session_workspace_projects",
        ["session_workspace_project_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_session_git_worktrees_session_id_status",
        "session_git_worktrees",
        ["session_id", "status"],
    )
    op.create_index(
        "ix_session_git_worktrees_session_workspace_project_id",
        "session_git_worktrees",
        ["session_workspace_project_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_session_git_worktrees_session_workspace_project_id",
        table_name="session_git_worktrees",
    )
    op.drop_index(
        "ix_session_git_worktrees_session_id_status",
        table_name="session_git_worktrees",
    )
    op.drop_constraint(
        "fk_session_git_worktrees_session_workspace_project_id",
        "session_git_worktrees",
        type_="foreignkey",
    )
    op.drop_column("session_git_worktrees", "session_workspace_project_id")
    op.create_unique_constraint(
        "uq_session_git_worktrees_session_id",
        "session_git_worktrees",
        ["session_id"],
    )
