"""remove runtime current session

Revision ID: 16e455dd8459
Revises: 6e2d8a4e22fd
Create Date: 2026-06-25 05:21:37.073938

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "16e455dd8459"
down_revision: str | Sequence[str] | None = "6e2d8a4e22fd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove runtime-owned session selection."""
    op.drop_constraint(
        "fk_agent_runtimes_current_session_id_agent_sessions",
        "agent_runtimes",
        type_="foreignkey",
    )
    op.drop_index("ix_agent_runtimes_current_session_id", table_name="agent_runtimes")
    op.drop_column("agent_runtimes", "current_session_id")


def downgrade() -> None:
    """Restore nullable runtime current-session pointer."""
    op.add_column(
        "agent_runtimes",
        sa.Column("current_session_id", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_agent_runtimes_current_session_id",
        "agent_runtimes",
        ["current_session_id"],
    )
    op.create_foreign_key(
        "fk_agent_runtimes_current_session_id_agent_sessions",
        "agent_runtimes",
        "agent_sessions",
        ["current_session_id"],
        ["id"],
        ondelete="SET NULL",
    )
