"""add agent run retry state

Revision ID: 1a2b3c4d5e6f
Revises: 8dfc9b5e1a2c
Create Date: 2026-06-28 13:55:00.000000

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "1a2b3c4d5e6f"
down_revision: str | Sequence[str] | None = "8dfc9b5e1a2c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add durable retry state to agent_runs."""
    op.add_column(
        "agent_runs",
        sa.Column(
            "retry_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )


def downgrade() -> None:
    """Remove durable retry state from agent_runs."""
    op.drop_column("agent_runs", "retry_state")
