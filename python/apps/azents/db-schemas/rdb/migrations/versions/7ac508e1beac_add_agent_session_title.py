"""add agent session title

Revision ID: 7ac508e1beac
Revises: 507bf6d9321d
Create Date: 2026-06-26 10:15:59.695179

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7ac508e1beac"
down_revision: str | Sequence[str] | None = "507bf6d9321d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable user-facing title to AgentSession."""
    op.add_column(
        "agent_sessions",
        sa.Column("title", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    """Remove user-facing title from AgentSession."""
    op.drop_column("agent_sessions", "title")
