"""add agent raw session type

Revision ID: abd47854fe61
Revises: fec6a18a2b7c
Create Date: 2026-05-04 00:02:15.499354

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "abd47854fe61"
down_revision: str | Sequence[str] | None = "fec6a18a2b7c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the enum value and unique index for the agent raw session bridge."""
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE conversation_session_type ADD VALUE IF NOT EXISTS 'agent'"
        )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "uq_conversation_sessions_agent_raw_session_agent_id "
        "ON conversation_sessions (agent_id) WHERE type = 'agent'"
    )


def downgrade() -> None:
    """Remove the index. Deleting PostgreSQL ENUM values is not supported."""
    op.execute(
        "DROP INDEX IF EXISTS uq_conversation_sessions_agent_raw_session_agent_id"
    )
