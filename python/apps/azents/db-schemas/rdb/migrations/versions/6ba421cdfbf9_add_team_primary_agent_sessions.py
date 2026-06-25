"""add team primary agent sessions

Revision ID: 6ba421cdfbf9
Revises: 6e2d8a4e22fd
Create Date: 2026-06-25 10:36:02.390843

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "6ba421cdfbf9"
down_revision: str | Sequence[str] | None = "6e2d8a4e22fd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add team primary session semantics and remove runtime current session."""
    op.execute("CREATE TYPE agent_session_primary_kind AS ENUM ('team_primary')")
    op.add_column(
        "agent_sessions",
        sa.Column(
            "primary_kind",
            postgresql.ENUM(name="agent_session_primary_kind", create_type=False),
            nullable=True,
        ),
    )
    op.execute(
        """
        UPDATE agent_sessions s
        SET primary_kind = 'team_primary'
        FROM agent_runtimes ar
        WHERE ar.current_session_id = s.id
          AND s.status = 'active'
        """
    )
    op.execute(
        """
        UPDATE agent_sessions
        SET primary_kind = 'team_primary'
        WHERE status = 'active'
          AND primary_kind IS NULL
        """
    )
    op.create_index(
        "uq_agent_sessions_agent_active_team_primary",
        "agent_sessions",
        ["agent_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND primary_kind = 'team_primary'"),
    )

    op.drop_constraint(
        "fk_agent_runtimes_current_session_id_agent_sessions",
        "agent_runtimes",
        type_="foreignkey",
    )
    op.drop_index("ix_agent_runtimes_current_session_id", table_name="agent_runtimes")
    op.drop_column("agent_runtimes", "current_session_id")


def downgrade() -> None:
    """Restore runtime current session compatibility column."""
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
    op.execute(
        """
        UPDATE agent_runtimes ar
        SET current_session_id = s.id
        FROM agent_sessions s
        WHERE s.agent_runtime_id = ar.id
          AND s.status = 'active'
          AND s.primary_kind = 'team_primary'
        """
    )

    op.drop_index(
        "uq_agent_sessions_agent_active_team_primary",
        table_name="agent_sessions",
    )
    op.drop_column("agent_sessions", "primary_kind")
    op.execute("DROP TYPE agent_session_primary_kind")
