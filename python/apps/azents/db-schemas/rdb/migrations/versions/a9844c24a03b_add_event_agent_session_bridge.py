"""add event agent session bridge

Revision ID: a9844c24a03b
Revises: cb74afe5f751
Create Date: 2026-05-04 11:29:52.906767

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a9844c24a03b"
down_revision: str | Sequence[str] | None = "cb74afe5f751"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add an AgentSession bridge to events."""
    op.add_column(
        "events",
        sa.Column("agent_session_id", sa.String(length=32), nullable=True),
    )
    op.create_foreign_key(
        "fk_events_agent_session_id_agent_sessions",
        "events",
        "agent_sessions",
        ["agent_session_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_events_agent_session_id",
        "events",
        ["agent_session_id"],
    )
    op.execute(
        """
        UPDATE events AS e
        SET agent_session_id = cs.agent_session_id
        FROM conversation_sessions AS cs
        WHERE e.session_id = cs.id
          AND cs.agent_session_id IS NOT NULL
        """
    )


def downgrade() -> None:
    """Remove the events AgentSession bridge."""
    op.drop_index("ix_events_agent_session_id", table_name="events")
    op.drop_constraint(
        "fk_events_agent_session_id_agent_sessions",
        "events",
        type_="foreignkey",
    )
    op.drop_column("events", "agent_session_id")
