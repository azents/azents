"""Add Runtime Provider operational diagnostics."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "6e0b87045f7c"
down_revision: str | Sequence[str] | None = "cf821b7c4df8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable connection-generation diagnostic snapshot fields."""
    op.add_column(
        "runtime_provider_connections",
        sa.Column(
            "operational_diagnostics",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "runtime_provider_connections",
        sa.Column(
            "diagnostics_checked_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove connection-generation diagnostic snapshot fields."""
    op.drop_column("runtime_provider_connections", "diagnostics_checked_at")
    op.drop_column("runtime_provider_connections", "operational_diagnostics")
