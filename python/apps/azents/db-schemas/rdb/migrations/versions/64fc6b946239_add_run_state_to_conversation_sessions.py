"""add run_state to conversation_sessions

Revision ID: 64fc6b946239
Revises: 4e99b41b35bb
Create Date: 2026-04-20 11:34:39.981558

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from azents.rdb.types.datetime import TimeZoneDateTime

# revision identifiers, used by Alembic.
revision: str = "64fc6b946239"
down_revision: str | Sequence[str] | None = "4e99b41b35bb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    sa.Enum("idle", "running", name="conversation_session_run_state").create(
        op.get_bind()
    )
    op.add_column(
        "conversation_sessions",
        sa.Column(
            "run_state",
            postgresql.ENUM(
                "idle",
                "running",
                name="conversation_session_run_state",
                create_type=False,
            ),
            server_default="idle",
            nullable=False,
        ),
    )
    op.add_column(
        "conversation_sessions",
        sa.Column(
            "run_heartbeat_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_conversation_sessions_run_state_running",
        "conversation_sessions",
        ["run_heartbeat_at"],
        unique=False,
        postgresql_where=sa.text("run_state = 'running'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_conversation_sessions_run_state_running",
        table_name="conversation_sessions",
        postgresql_where=sa.text("run_state = 'running'"),
    )
    op.drop_column("conversation_sessions", "run_heartbeat_at")
    op.drop_column("conversation_sessions", "run_state")
    sa.Enum("idle", "running", name="conversation_session_run_state").drop(
        op.get_bind()
    )
