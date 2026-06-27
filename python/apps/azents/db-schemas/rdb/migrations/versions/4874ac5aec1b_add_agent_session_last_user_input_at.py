"""add agent session last user input at

Revision ID: 4874ac5aec1b
Revises: 9779e2e7f451
Create Date: 2026-06-27 01:09:00.880224

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4874ac5aec1b"
down_revision: str | Sequence[str] | None = "9779e2e7f451"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add latest user input timestamp to AgentSession."""
    op.add_column(
        "agent_sessions",
        sa.Column(
            "last_user_input_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
    )
    op.execute(
        """
        UPDATE agent_sessions AS agent_session
        SET last_user_input_at = coalesce(
            latest_user_input.created_at,
            agent_session.created_at
        )
        FROM (
            SELECT session_id, max(created_at) AS created_at
            FROM events
            WHERE kind = 'user_message' AND reverted = false
            GROUP BY session_id
        ) AS latest_user_input
        WHERE latest_user_input.session_id = agent_session.id
        """
    )
    op.execute(
        """
        UPDATE agent_sessions
        SET last_user_input_at = created_at
        WHERE last_user_input_at IS NULL
        """
    )
    op.alter_column("agent_sessions", "last_user_input_at", nullable=False)
    op.create_index(
        "ix_agent_sessions_agent_active_last_user_input",
        "agent_sessions",
        ["agent_id", "primary_kind", "last_user_input_at"],
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    """Remove latest user input timestamp from AgentSession."""
    op.drop_index(
        "ix_agent_sessions_agent_active_last_user_input",
        table_name="agent_sessions",
        postgresql_where=sa.text("status = 'active'"),
    )
    op.drop_column("agent_sessions", "last_user_input_at")
