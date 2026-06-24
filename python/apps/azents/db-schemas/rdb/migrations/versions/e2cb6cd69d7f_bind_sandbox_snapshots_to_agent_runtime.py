"""bind sandbox snapshots to agent runtime

Revision ID: e2cb6cd69d7f
Revises: 5a290e42b9c6
Create Date: 2026-05-05 17:08:45.460455

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2cb6cd69d7f"
down_revision: str | Sequence[str] | None = "5a290e42b9c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Switch sandbox snapshot lookup to use AgentRuntime as the basis."""
    op.add_column(
        "kubernetes_sandbox_snapshots",
        sa.Column("agent_runtime_id", sa.String(length=32), nullable=True),
    )
    op.execute(
        """
        UPDATE kubernetes_sandbox_snapshots AS snapshots
        SET agent_runtime_id = sessions.agent_runtime_id
        FROM agent_sessions AS sessions
        WHERE snapshots.agent_session_id = sessions.id
        """
    )
    op.alter_column(
        "kubernetes_sandbox_snapshots",
        "agent_runtime_id",
        nullable=False,
    )
    op.drop_index(
        "ix_kubernetes_sandbox_snapshots_agent_session_id_created_at",
        table_name="kubernetes_sandbox_snapshots",
    )
    op.create_index(
        "ix_kubernetes_sandbox_snapshots_agent_runtime_id_created_at",
        "kubernetes_sandbox_snapshots",
        ["agent_runtime_id", sa.literal_column("created_at DESC")],
    )
    op.drop_constraint(
        "kubernetes_sandbox_snapshots_agent_session_id_fkey",
        "kubernetes_sandbox_snapshots",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "kubernetes_sandbox_snapshots_agent_runtime_id_fkey",
        "kubernetes_sandbox_snapshots",
        "agent_runtimes",
        ["agent_runtime_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_column("kubernetes_sandbox_snapshots", "agent_session_id")


def downgrade() -> None:
    """Switch sandbox snapshot lookup back to use AgentSession as the basis."""
    op.add_column(
        "kubernetes_sandbox_snapshots",
        sa.Column("agent_session_id", sa.String(length=32), nullable=True),
    )
    op.execute(
        """
        UPDATE kubernetes_sandbox_snapshots AS snapshots
        SET agent_session_id = runtimes.current_session_id
        FROM agent_runtimes AS runtimes
        WHERE snapshots.agent_runtime_id = runtimes.id
        """
    )
    op.alter_column(
        "kubernetes_sandbox_snapshots",
        "agent_session_id",
        nullable=False,
    )
    op.drop_constraint(
        "kubernetes_sandbox_snapshots_agent_runtime_id_fkey",
        "kubernetes_sandbox_snapshots",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_kubernetes_sandbox_snapshots_agent_runtime_id_created_at",
        table_name="kubernetes_sandbox_snapshots",
    )
    op.create_foreign_key(
        "kubernetes_sandbox_snapshots_agent_session_id_fkey",
        "kubernetes_sandbox_snapshots",
        "agent_sessions",
        ["agent_session_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_kubernetes_sandbox_snapshots_agent_session_id_created_at",
        "kubernetes_sandbox_snapshots",
        ["agent_session_id", sa.literal_column("created_at DESC")],
    )
    op.drop_column("kubernetes_sandbox_snapshots", "agent_runtime_id")
