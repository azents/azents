"""add session auto archive fields

Revision ID: 10d8111b556c
Revises: 8bbe580fddad
Create Date: 2026-07-26 18:09:39.071437

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "10d8111b556c"
down_revision: str | Sequence[str] | None = "8bbe580fddad"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "agents",
        sa.Column(
            "auto_archive_ttl_days",
            sa.Integer(),
            server_default="30",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_agents_auto_archive_ttl_days_positive",
        "agents",
        "auto_archive_ttl_days > 0",
    )
    op.add_column(
        "agent_sessions",
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE agent_sessions
        SET last_activity_at = GREATEST(
            last_user_input_at,
            started_at,
            created_at,
            updated_at
        )
        """
    )
    op.alter_column(
        "agent_sessions",
        "last_activity_at",
        nullable=False,
        server_default=sa.text("now()"),
    )
    op.add_column(
        "agent_sessions",
        sa.Column("pinned", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_index(
        "ix_agent_sessions_active_auto_archive",
        "agent_sessions",
        ["last_activity_at", "agent_id"],
        postgresql_where=sa.text(
            "status = 'active' AND session_kind = 'root' AND pinned = false"
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_agent_sessions_active_auto_archive", "agent_sessions")
    op.drop_column("agent_sessions", "pinned")
    op.drop_column("agent_sessions", "last_activity_at")
    op.drop_constraint(
        "ck_agents_auto_archive_ttl_days_positive",
        "agents",
        type_="check",
    )
    op.drop_column("agents", "auto_archive_ttl_days")
