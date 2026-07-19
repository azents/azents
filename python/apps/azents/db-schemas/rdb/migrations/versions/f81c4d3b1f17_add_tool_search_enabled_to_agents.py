"""Add Tool Search enabled setting to Agents."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f81c4d3b1f17"
down_revision: str | Sequence[str] | None = "7e9b625b4c81"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "agents",
        sa.Column(
            "tool_search_enabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("agents", "tool_search_enabled")
