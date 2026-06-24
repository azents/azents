"""add last_activity_at to conversation_sessions

Revision ID: c2ea1992a602
Revises: 0057dab8a446
Create Date: 2026-04-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c2ea1992a602"
down_revision: str | None = "0057dab8a446"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Step 1: add as a nullable column first to minimize lock time on large tables
    op.add_column(
        "conversation_sessions",
        sa.Column(
            "last_activity_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )
    # Step 2: backfill existing rows using updated_at as the initial value
    op.execute(
        """
        UPDATE conversation_sessions
        SET last_activity_at = updated_at
        WHERE last_activity_at IS NULL
        """
    )
    # Step 3: promote to NOT NULL with default NOW()
    op.alter_column(
        "conversation_sessions",
        "last_activity_at",
        nullable=False,
        server_default=sa.text("now()"),
    )
    # Composite index covering idle agent detection queries
    op.create_index(
        "ix_conversation_sessions_agent_id_last_activity_at",
        "conversation_sessions",
        ["agent_id", "last_activity_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversation_sessions_agent_id_last_activity_at",
        table_name="conversation_sessions",
    )
    op.drop_column("conversation_sessions", "last_activity_at")
