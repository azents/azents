"""Add per-Agent encrypted Runtime environment settings."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4bf6286235d"
down_revision: str | Sequence[str] | None = "e89fba791b40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add an empty Agent setting without moving any Toolkit credentials."""
    op.add_column(
        "agents", sa.Column("encrypted_runtime_environment", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    """Remove the added settings column."""
    op.drop_column("agents", "encrypted_runtime_environment")
