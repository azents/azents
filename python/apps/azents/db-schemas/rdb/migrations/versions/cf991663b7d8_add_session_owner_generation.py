"""Add session owner generation."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "cf991663b7d8"
down_revision: str | Sequence[str] | None = "d0f03808195a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "agent_sessions",
        sa.Column(
            "owner_generation",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("agent_sessions", "owner_generation")
