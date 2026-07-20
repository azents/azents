"""Add shared unread terminal Run state for AgentSessions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "22f0f04e5ec0"
down_revision: str | Sequence[str] | None = "c0a51320cfdb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "agent_session_unread_runs",
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("run_index", sa.BigInteger(), nullable=False),
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
        sa.CheckConstraint(
            "run_index > 0",
            name="ck_agent_session_unread_runs_run_index_positive",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["agent_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("session_id"),
        sa.UniqueConstraint("run_id", name="uq_agent_session_unread_runs_run_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("agent_session_unread_runs")
