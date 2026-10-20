"""Retain unresolved Agent deletion failure attribution across retry claims."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2944b0e66140"
down_revision: str | Sequence[str] | None = "7a17e11b4260"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add attribution without guessing the owner of historical diagnostics."""
    op.add_column(
        "agent_decommission_jobs",
        sa.Column("failure_boundary_key", sa.String(512), nullable=True),
    )


def downgrade() -> None:
    """Remove attribution only after rolling back application writers."""
    op.drop_column("agent_decommission_jobs", "failure_boundary_key")
