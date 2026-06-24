"""Remove deprecated external conversation session types.

Revision ID: 9ddc078c204a
Revises: 3208e4d784c8
Create Date: 2026-05-05 01:41:20.487088

"""

from typing import Sequence

from alembic import op

revision: str = "9ddc078c204a"
down_revision: str | Sequence[str] | None = "3208e4d784c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove deprecated external channel session rows and ENUM values."""
    op.execute(
        "DELETE FROM conversation_sessions WHERE type::text IN ('slack', 'discord')"
    )
    op.execute(
        "DROP INDEX IF EXISTS uq_conversation_sessions_agent_raw_session_agent_id"
    )
    op.execute(
        "ALTER TYPE conversation_session_type RENAME TO conversation_session_type_old"
    )
    op.execute(
        "CREATE TYPE conversation_session_type AS ENUM ('web', 'subagent', 'agent')"
    )
    op.execute(
        "ALTER TABLE conversation_sessions "
        "ALTER COLUMN type TYPE conversation_session_type "
        "USING type::text::conversation_session_type"
    )
    op.execute("DROP TYPE conversation_session_type_old")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "uq_conversation_sessions_agent_raw_session_agent_id "
        "ON conversation_sessions (agent_id) WHERE type = 'agent'"
    )


def downgrade() -> None:
    """Restore the external channel session type ENUM values."""
    op.execute(
        "DROP INDEX IF EXISTS uq_conversation_sessions_agent_raw_session_agent_id"
    )
    op.execute(
        "ALTER TYPE conversation_session_type RENAME TO conversation_session_type_old"
    )
    op.execute(
        "CREATE TYPE conversation_session_type AS ENUM "
        "('web', 'subagent', 'slack', 'discord', 'agent')"
    )
    op.execute(
        "ALTER TABLE conversation_sessions "
        "ALTER COLUMN type TYPE conversation_session_type "
        "USING type::text::conversation_session_type"
    )
    op.execute("DROP TYPE conversation_session_type_old")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "uq_conversation_sessions_agent_raw_session_agent_id "
        "ON conversation_sessions (agent_id) WHERE type = 'agent'"
    )
