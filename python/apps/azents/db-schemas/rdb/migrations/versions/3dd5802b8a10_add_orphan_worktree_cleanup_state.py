"""add orphan worktree cleanup state

Revision ID: 3dd5802b8a10
Revises: cc31dfa97a1b
Create Date: 2026-07-26 05:10:20.918873

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "3dd5802b8a10"
down_revision: str | Sequence[str] | None = "cc31dfa97a1b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

git_worktree_path_claim_owner_kind = postgresql.ENUM(
    "manual_action",
    "archive_cleanup",
    name="git_worktree_path_claim_owner_kind",
)
git_worktree_path_claim_owner_kind_column = postgresql.ENUM(
    "manual_action",
    "archive_cleanup",
    name="git_worktree_path_claim_owner_kind",
    create_type=False,
)
git_worktree_path_claim_state = postgresql.ENUM(
    "claimed",
    "removing",
    "removed",
    "already_absent",
    "failed",
    "unresolved",
    name="git_worktree_path_claim_state",
)
git_worktree_path_claim_state_column = postgresql.ENUM(
    "claimed",
    "removing",
    "removed",
    "already_absent",
    "failed",
    "unresolved",
    name="git_worktree_path_claim_state",
    create_type=False,
)


def upgrade() -> None:
    """Add structured TurnAction result storage and cleanup claims."""
    op.add_column(
        "action_executions",
        sa.Column("result", postgresql.JSONB(), nullable=True),
    )
    bind = op.get_bind()
    git_worktree_path_claim_owner_kind.create(bind, checkfirst=True)
    git_worktree_path_claim_state.create(bind, checkfirst=True)
    op.create_table(
        "git_worktree_path_claims",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("agent_runtime_id", sa.String(length=32), nullable=False),
        sa.Column("worktree_path", sa.Text(), nullable=False),
        sa.Column(
            "owner_kind",
            git_worktree_path_claim_owner_kind_column,
            nullable=False,
        ),
        sa.Column("action_execution_id", sa.String(length=32), nullable=True),
        sa.Column("root_session_id", sa.String(length=32), nullable=True),
        sa.Column("owner_generation", sa.BigInteger(), nullable=True),
        sa.Column("discovery_fingerprint", sa.Text(), nullable=True),
        sa.Column(
            "state",
            git_worktree_path_claim_state_column,
            nullable=False,
        ),
        sa.Column("reason_code", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["action_execution_id"],
            ["action_executions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["agent_runtime_id"],
            ["agent_runtimes.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["root_session_id"],
            ["agent_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_runtime_id",
            "worktree_path",
            name="uq_git_worktree_path_claims_agent_runtime_path",
        ),
    )
    op.create_index(
        "ix_git_worktree_path_claims_action_execution_id",
        "git_worktree_path_claims",
        ["action_execution_id"],
    )
    op.create_index(
        "ix_git_worktree_path_claims_agent_runtime_id",
        "git_worktree_path_claims",
        ["agent_runtime_id"],
    )
    op.create_index(
        "ix_git_worktree_path_claims_root_session_id",
        "git_worktree_path_claims",
        ["root_session_id"],
    )


def downgrade() -> None:
    """Remove cleanup claims and structured TurnAction result storage."""
    op.drop_index(
        "ix_git_worktree_path_claims_root_session_id",
        table_name="git_worktree_path_claims",
    )
    op.drop_index(
        "ix_git_worktree_path_claims_agent_runtime_id",
        table_name="git_worktree_path_claims",
    )
    op.drop_index(
        "ix_git_worktree_path_claims_action_execution_id",
        table_name="git_worktree_path_claims",
    )
    op.drop_table("git_worktree_path_claims")
    postgresql.ENUM(name="git_worktree_path_claim_state").drop(
        op.get_bind(),
        checkfirst=False,
    )
    postgresql.ENUM(name="git_worktree_path_claim_owner_kind").drop(
        op.get_bind(),
        checkfirst=False,
    )
    op.drop_column("action_executions", "result")
