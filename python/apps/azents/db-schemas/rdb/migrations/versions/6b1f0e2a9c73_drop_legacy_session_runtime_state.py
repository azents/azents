"""drop legacy session runtime state

Revision ID: 6b1f0e2a9c73
Revises: 4b9c3ddc0e5a
Create Date: 2026-05-26 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "6b1f0e2a9c73"
down_revision: str | Sequence[str] | None = "4b9c3ddc0e5a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove legacy session-scoped runtime lifecycle columns."""
    op.drop_index(
        "ix_agent_runtimes_runtime_state_deadline",
        table_name="agent_runtimes",
    )
    op.drop_index(
        "ix_agent_runtimes_runtime_claimed_at",
        table_name="agent_runtimes",
    )
    op.drop_column("agent_runtimes", "snapshot_deadline_at")
    op.drop_column("agent_runtimes", "last_runtime_change_at")
    op.drop_column("agent_runtimes", "runtime_claimed_at")
    op.drop_column("agent_runtimes", "runtime_state")
    op.drop_column("agent_runtimes", "runtime_run_id")
    op.execute("DROP TYPE IF EXISTS session_runtime_state")


def downgrade() -> None:
    """Restore legacy session-scoped runtime lifecycle columns."""
    session_runtime_state = postgresql.ENUM(
        "active",
        "persisting",
        "hibernated",
        "restoring",
        "expired",
        name="session_runtime_state",
    )
    session_runtime_state.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "agent_runtimes",
        sa.Column("runtime_run_id", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column(
            "runtime_state",
            postgresql.ENUM(name="session_runtime_state", create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column("runtime_claimed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column("last_runtime_change_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column("snapshot_deadline_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_agent_runtimes_runtime_claimed_at",
        "agent_runtimes",
        ["runtime_claimed_at"],
        postgresql_where=sa.text("runtime_run_id IS NOT NULL"),
    )
    op.create_index(
        "ix_agent_runtimes_runtime_state_deadline",
        "agent_runtimes",
        ["runtime_state", "snapshot_deadline_at"],
        postgresql_where=sa.text("runtime_state = 'active'"),
    )
