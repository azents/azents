"""remove agent session runtime ownership

Revision ID: 97e8d03b0e20
Revises: 6ba421cdfbf9
Create Date: 2026-06-25 13:33:56.091676

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "97e8d03b0e20"
down_revision: str | Sequence[str] | None = "6ba421cdfbf9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove AgentSession runtime ownership edge."""
    op.execute(
        """
        UPDATE agent_sessions
        SET start_reason = 'initial'
        WHERE start_reason IN ('manual_new', 'manual_reset', 'compact_rotate')
        """
    )
    op.execute(
        """
        UPDATE agent_sessions
        SET end_reason = 'deleted'
        WHERE end_reason IN ('manual_new', 'manual_reset', 'compact_rotate')
        """
    )
    op.drop_index("uq_agent_sessions_runtime_active", table_name="agent_sessions")
    op.drop_index("ix_agent_sessions_agent_runtime_id", table_name="agent_sessions")
    op.drop_constraint(
        "fk_agent_sessions_agent_runtime_id_agent_runtimes",
        "agent_sessions",
        type_="foreignkey",
    )
    op.drop_column("agent_sessions", "agent_runtime_id")


def downgrade() -> None:
    """Restore AgentSession runtime ownership for older application versions."""
    op.add_column(
        "agent_sessions",
        sa.Column("agent_runtime_id", sa.String(length=32), nullable=True),
    )
    op.execute(
        """
        UPDATE agent_sessions s
        SET agent_runtime_id = ar.id
        FROM agent_runtimes ar
        WHERE ar.agent_id = s.agent_id
        """
    )
    op.execute("DELETE FROM agent_sessions WHERE agent_runtime_id IS NULL")
    op.alter_column("agent_sessions", "agent_runtime_id", nullable=False)
    op.create_foreign_key(
        "fk_agent_sessions_agent_runtime_id_agent_runtimes",
        "agent_sessions",
        "agent_runtimes",
        ["agent_runtime_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_agent_sessions_agent_runtime_id",
        "agent_sessions",
        ["agent_runtime_id"],
    )
    op.create_index(
        "uq_agent_sessions_runtime_active",
        "agent_sessions",
        ["agent_runtime_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
