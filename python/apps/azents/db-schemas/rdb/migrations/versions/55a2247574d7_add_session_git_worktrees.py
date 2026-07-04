"""add session git worktrees

Revision ID: 55a2247574d7
Revises: d05b0f8874f4
Create Date: 2026-07-03 22:59:16.633076

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "55a2247574d7"
down_revision: str | Sequence[str] | None = "d05b0f8874f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SESSION_GIT_WORKTREE_STATUS_VALUES = (
    "pending",
    "creating",
    "ready",
    "failed",
    "cleanup_pending",
    "cleaned",
    "cleanup_failed",
)
SESSION_GIT_WORKTREE_BRANCH_CREATED_BY_VALUES = ("azents",)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    postgresql.ENUM(
        *SESSION_GIT_WORKTREE_STATUS_VALUES,
        name="session_git_worktree_status",
    ).create(bind)
    postgresql.ENUM(
        *SESSION_GIT_WORKTREE_BRANCH_CREATED_BY_VALUES,
        name="session_git_worktree_branch_created_by",
    ).create(bind)

    op.create_table(
        "session_git_worktrees",
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("initialization_id", sa.String(length=32), nullable=False),
        sa.Column("step_id", sa.String(length=32), nullable=False),
        sa.Column("source_project_path", sa.Text(), nullable=False),
        sa.Column("starting_ref", sa.Text(), nullable=False),
        sa.Column("worktree_path", sa.Text(), nullable=False),
        sa.Column("branch_name", sa.Text(), nullable=False),
        sa.Column(
            "branch_created_by",
            postgresql.ENUM(
                name="session_git_worktree_branch_created_by",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                name="session_git_worktree_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("base_commit", sa.String(length=64), nullable=True),
        sa.Column("failure_summary", sa.Text(), nullable=True),
        sa.Column("cleanup_summary", sa.Text(), nullable=True),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cleaned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["initialization_id"],
            ["session_initializations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["agent_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["step_id"],
            ["session_initialization_steps.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            name="uq_session_git_worktrees_session_id",
        ),
    )
    op.create_index(
        "ix_session_git_worktrees_session_id",
        "session_git_worktrees",
        ["session_id"],
    )
    op.create_index(
        "ix_session_git_worktrees_status",
        "session_git_worktrees",
        ["status"],
    )
    op.create_index(
        "ix_session_git_worktrees_worktree_path",
        "session_git_worktrees",
        ["worktree_path"],
    )
    op.create_index(
        "ix_session_git_worktrees_branch_name",
        "session_git_worktrees",
        ["branch_name"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_session_git_worktrees_branch_name",
        table_name="session_git_worktrees",
    )
    op.drop_index(
        "ix_session_git_worktrees_worktree_path",
        table_name="session_git_worktrees",
    )
    op.drop_index(
        "ix_session_git_worktrees_status",
        table_name="session_git_worktrees",
    )
    op.drop_index(
        "ix_session_git_worktrees_session_id",
        table_name="session_git_worktrees",
    )
    op.drop_table("session_git_worktrees")

    bind = op.get_bind()
    postgresql.ENUM(name="session_git_worktree_branch_created_by").drop(bind)
    postgresql.ENUM(name="session_git_worktree_status").drop(bind)
