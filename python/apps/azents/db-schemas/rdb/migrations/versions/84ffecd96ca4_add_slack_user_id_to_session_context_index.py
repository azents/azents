"""add slack_user_id to session context index

Revision ID: 84ffecd96ca4
Revises: 61d68c3ce6fc
Create Date: 2026-03-09 12:00:00.000000

"""

from typing import Sequence

from alembic import op

revision: str = "84ffecd96ca4"
down_revision: str | Sequence[str] | None = "61d68c3ce6fc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index("ix_slack_sessions_context", table_name="slack_sessions")
    op.create_index(
        "ix_slack_sessions_context",
        "slack_sessions",
        ["installation_id", "slack_channel_id", "slack_thread_ts", "slack_user_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_slack_sessions_context", table_name="slack_sessions")
    op.create_index(
        "ix_slack_sessions_context",
        "slack_sessions",
        ["installation_id", "slack_channel_id", "slack_thread_ts"],
    )
