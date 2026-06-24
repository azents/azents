"""rename_user_to_web_and_remove_system_session_type

Revision ID: 4e99b41b35bb
Revises: ec349cf64a15
Create Date: 2026-04-19 14:10:15.054992

"""

# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4e99b41b35bb"
down_revision: str | Sequence[str] | None = "ec349cf64a15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Redefine the conversation_session_type ENUM.

    - Rename 'user' to 'web'
    - Remove the 'system' value, which was never used
    """
    # Rename 'user' to 'web' (PG 10+)
    op.execute("ALTER TYPE conversation_session_type RENAME VALUE 'user' TO 'web'")

    # Remove 'system': PostgreSQL cannot delete ENUM values, so recreate it
    op.execute(
        "ALTER TYPE conversation_session_type RENAME TO conversation_session_type_old"
    )
    op.execute(
        "CREATE TYPE conversation_session_type AS ENUM "
        "('web', 'subagent', 'slack', 'discord')"
    )
    op.execute(
        "ALTER TABLE conversation_sessions "
        "ALTER COLUMN type TYPE conversation_session_type "
        "USING type::text::conversation_session_type"
    )
    op.execute("DROP TYPE conversation_session_type_old")


def downgrade() -> None:
    """Restore the previous ENUM state (user/system/subagent/slack/discord)."""
    op.execute(
        "ALTER TYPE conversation_session_type RENAME TO conversation_session_type_old"
    )
    op.execute(
        "CREATE TYPE conversation_session_type AS ENUM "
        "('user', 'system', 'subagent', 'slack', 'discord')"
    )
    op.execute(
        "ALTER TABLE conversation_sessions "
        "ALTER COLUMN type TYPE conversation_session_type "
        "USING (CASE WHEN type::text = 'web' THEN 'user' "
        "ELSE type::text END)::conversation_session_type"
    )
    op.execute("DROP TYPE conversation_session_type_old")
