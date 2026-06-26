"""add agent session title source

Revision ID: 9779e2e7f451
Revises: 7ac508e1beac
Create Date: 2026-06-26 15:09:06.173232

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "9779e2e7f451"
down_revision: str | Sequence[str] | None = "7ac508e1beac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add AgentSession title source metadata."""
    title_source_enum = postgresql.ENUM(
        "manual",
        "auto_initial",
        "auto_generated",
        name="agent_session_title_source",
    )
    title_source_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "agent_sessions",
        sa.Column(
            "title_source",
            title_source_enum,
            nullable=True,
        ),
    )
    op.add_column(
        "agent_sessions",
        sa.Column("title_generated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agent_sessions",
        sa.Column("title_generation_event_id", sa.String(length=32), nullable=True),
    )
    op.execute(
        "UPDATE agent_sessions SET title_source = 'manual' WHERE title IS NOT NULL"
    )


def downgrade() -> None:
    """Remove AgentSession title source metadata."""
    op.drop_column("agent_sessions", "title_generation_event_id")
    op.drop_column("agent_sessions", "title_generated_at")
    op.drop_column("agent_sessions", "title_source")
    title_source_enum = postgresql.ENUM(
        "manual",
        "auto_initial",
        "auto_generated",
        name="agent_session_title_source",
    )
    title_source_enum.drop(op.get_bind(), checkfirst=True)
