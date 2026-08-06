"""add agent session product mode and associated user

Revision ID: 2a9ad984951f
Revises: d51acb332a07
Create Date: 2026-08-06 08:54:02.526734

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2a9ad984951f"
down_revision: str | Sequence[str] | None = "d51acb332a07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add root product mode, associated user, and Team backfill."""
    op.execute("CREATE TYPE agent_session_product_mode AS ENUM ('team', 'user')")
    op.add_column(
        "agent_sessions",
        sa.Column(
            "product_mode",
            postgresql.ENUM(name="agent_session_product_mode", create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_sessions",
        sa.Column("associated_user_id", sa.String(length=32), nullable=True),
    )
    op.execute(
        """
        UPDATE agent_sessions
        SET product_mode = 'team',
            associated_user_id = NULL
        WHERE session_kind = 'root'
        """
    )
    op.execute(
        """
        UPDATE agent_sessions
        SET product_mode = NULL,
            associated_user_id = NULL
        WHERE session_kind = 'subagent'
        """
    )
    op.create_foreign_key(
        "fk_agent_sessions_associated_user_id_users",
        "agent_sessions",
        "users",
        ["associated_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_agent_sessions_product_mode_ownership",
        "agent_sessions",
        "("
        "session_kind = 'root' "
        "AND product_mode = 'team' "
        "AND associated_user_id IS NULL"
        ") OR ("
        "session_kind = 'root' "
        "AND product_mode = 'user' "
        "AND associated_user_id IS NOT NULL "
        "AND primary_kind IS NULL"
        ") OR ("
        "session_kind = 'subagent' "
        "AND product_mode IS NULL "
        "AND associated_user_id IS NULL "
        "AND primary_kind IS NULL"
        ")",
    )
    op.drop_index(
        "uq_agent_sessions_agent_active_team_primary",
        table_name="agent_sessions",
    )
    op.create_index(
        "uq_agent_sessions_agent_active_team_primary",
        "agent_sessions",
        ["agent_id"],
        unique=True,
        postgresql_where=sa.text(
            "status = 'active' "
            "AND primary_kind = 'team_primary' "
            "AND product_mode = 'team'"
        ),
    )
    op.create_index(
        "ix_agent_sessions_agent_associated_user_status",
        "agent_sessions",
        ["agent_id", "associated_user_id", "status"],
    )
    op.create_index(
        "ix_agent_sessions_associated_user_id",
        "agent_sessions",
        ["associated_user_id"],
    )


def downgrade() -> None:
    """Remove root product mode and associated user."""
    op.drop_index(
        "ix_agent_sessions_associated_user_id",
        table_name="agent_sessions",
    )
    op.drop_index(
        "ix_agent_sessions_agent_associated_user_status",
        table_name="agent_sessions",
    )
    op.drop_index(
        "uq_agent_sessions_agent_active_team_primary",
        table_name="agent_sessions",
    )
    op.create_index(
        "uq_agent_sessions_agent_active_team_primary",
        "agent_sessions",
        ["agent_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND primary_kind = 'team_primary'"),
    )
    op.drop_constraint(
        "ck_agent_sessions_product_mode_ownership",
        "agent_sessions",
        type_="check",
    )
    op.drop_constraint(
        "fk_agent_sessions_associated_user_id_users",
        "agent_sessions",
        type_="foreignkey",
    )
    op.drop_column("agent_sessions", "associated_user_id")
    op.drop_column("agent_sessions", "product_mode")
    op.execute("DROP TYPE agent_session_product_mode")
