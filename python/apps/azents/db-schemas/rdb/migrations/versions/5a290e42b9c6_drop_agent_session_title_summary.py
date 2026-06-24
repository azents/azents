"""drop agent session title summary

Revision ID: 5a290e42b9c6
Revises: 15d2350fe2e4
Create Date: 2026-05-05 16:54:53.122225

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5a290e42b9c6"
down_revision: str | Sequence[str] | None = "15d2350fe2e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove the AgentSession title and summary columns."""
    op.drop_column("agent_sessions", "summary")
    op.drop_column("agent_sessions", "title")


def downgrade() -> None:
    """Restore the AgentSession title and summary columns."""
    op.add_column(
        "agent_sessions",
        sa.Column("title", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "agent_sessions",
        sa.Column("summary", sa.Text(), nullable=True),
    )
