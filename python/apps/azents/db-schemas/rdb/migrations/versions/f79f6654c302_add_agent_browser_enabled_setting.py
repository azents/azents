"""Add the independent Agent Browser setting."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f79f6654c302"
down_revision: str | Sequence[str] | None = "409e9e3cb85a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "agents",
        sa.Column(
            "browser_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("agents", "browser_enabled")
