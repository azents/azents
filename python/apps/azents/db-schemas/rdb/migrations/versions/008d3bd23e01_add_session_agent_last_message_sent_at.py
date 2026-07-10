"""add session agent last message sent at

Revision ID: 008d3bd23e01
Revises: b754406b3aee
Create Date: 2026-07-10 05:01:31.269947

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "008d3bd23e01"
down_revision: str | Sequence[str] | None = "b754406b3aee"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add and backfill the latest agent-to-agent message sent time."""
    op.add_column(
        "session_agents",
        sa.Column(
            "last_message_sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.execute(
        """
        UPDATE session_agents AS session_agent
        SET last_message_sent_at = latest_message.created_at
        FROM (
            SELECT
                payload ->> 'source_session_agent_id' AS session_agent_id,
                max(created_at) AS created_at
            FROM events
            WHERE kind = 'agent_message' AND reverted = false
            GROUP BY payload ->> 'source_session_agent_id'
        ) AS latest_message
        WHERE latest_message.session_agent_id = session_agent.id
        """
    )


def downgrade() -> None:
    """Remove the latest agent-to-agent message sent time."""
    op.drop_column("session_agents", "last_message_sent_at")
