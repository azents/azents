"""store latest session system prompt

Revision ID: 6412e7bf0530
Revises: c4e49a389b5c
Create Date: 2026-07-21 12:51:09.879257

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from azents.rdb.types.datetime import TimeZoneDateTime

# revision identifiers, used by Alembic.
revision: str = "6412e7bf0530"
down_revision: str | Sequence[str] | None = "c4e49a389b5c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create current session prompt snapshots and remove transcript duplicates."""
    op.create_table(
        "agent_session_system_prompt_snapshots",
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column(
            "system_prompt",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            TimeZoneDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            TimeZoneDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["agent_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("session_id"),
    )


def downgrade() -> None:
    """Drop snapshots without reconstructing discarded prompt history."""
    op.drop_table("agent_session_system_prompt_snapshots")
