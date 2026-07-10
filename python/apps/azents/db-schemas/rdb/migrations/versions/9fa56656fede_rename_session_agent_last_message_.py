"""rename session agent last message activity

Revision ID: 9fa56656fede
Revises: 008d3bd23e01
Create Date: 2026-07-10 06:03:01.315916

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9fa56656fede"
down_revision: str | Sequence[str] | None = "008d3bd23e01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Rename the durable agent communication activity timestamp."""
    op.alter_column(
        "session_agents",
        "last_message_sent_at",
        new_column_name="last_message_at",
    )
    op.execute(
        """
        UPDATE session_agents AS session_agent
        SET last_message_at = latest_activity.created_at
        FROM (
            SELECT
                participant.session_agent_id,
                max(participant.created_at) AS created_at
            FROM (
                SELECT
                    payload ->> 'source_session_agent_id' AS session_agent_id,
                    created_at
                FROM events
                WHERE kind = 'agent_message' AND reverted = false
                UNION ALL
                SELECT
                    payload ->> 'target_session_agent_id' AS session_agent_id,
                    created_at
                FROM events
                WHERE kind = 'agent_message' AND reverted = false
            ) AS participant
            WHERE participant.session_agent_id IS NOT NULL
            GROUP BY participant.session_agent_id
        ) AS latest_activity
        WHERE latest_activity.session_agent_id = session_agent.id
        """
    )


def downgrade() -> None:
    """Restore the previous sent-message-only timestamp."""
    op.alter_column(
        "session_agents",
        "last_message_at",
        new_column_name="last_message_sent_at",
    )
    op.execute("UPDATE session_agents SET last_message_sent_at = NULL")
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
