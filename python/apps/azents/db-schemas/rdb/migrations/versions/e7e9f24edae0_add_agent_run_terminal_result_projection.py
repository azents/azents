"""add agent run terminal result projection

Revision ID: e7e9f24edae0
Revises: 5042746274a0
Create Date: 2026-07-08 10:47:14.652685

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7e9f24edae0"
down_revision: str | Sequence[str] | None = "5042746274a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "agent_runs",
        sa.Column("terminal_result_event_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column("terminal_result_message", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("agent_runs", "terminal_result_message")
    op.drop_column("agent_runs", "terminal_result_event_id")
